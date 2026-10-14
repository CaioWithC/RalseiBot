import asyncio
import csv
import hashlib
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
import nextcord
from nextcord.ext import commands

from cogs.command_support import DualCommand
from db import DAILY_TIMEZONE, EconomyError

log = logging.getLogger(__name__)
PLAYLIST_PATH = Path(__file__).resolve().parent.parent / "assets" / "playlist.csv"
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/release-group/"
COVER_ART_URL = "https://coverartarchive.org/release-group/{mbid}"
USER_AGENT = "RalseiBot/1.0 (https://github.com/CaioWithC/RalseiBot)"


def load_playlist(path=PLAYLIST_PATH):
    try:
        with path.open(encoding="utf-8-sig", newline="") as playlist_file:
            reader = csv.DictReader(playlist_file)
            songs = []
            for row_number, row in enumerate(reader, start=2):
                if not any(value and value.strip() for value in row.values()):
                    continue
                title = (row.get("Track name") or "").strip()
                artist = (row.get("Artist name") or "").strip()
                if not title or not artist:
                    raise EconomyError(
                        f"A playlist precisa ter título e artista preenchidos (linha {row_number})."
                    )
                songs.append({
                    "title": title,
                    "artist": artist,
                    "album": (row.get("Album") or "").strip(),
                    "spotify_id": (row.get("Spotify - id") or "").strip(),
                })
    except OSError as error:
        log.error("Could not read music playlist at %s", path, exc_info=True)
        raise EconomyError("Não consegui carregar a playlist de músicas.") from error

    if not songs:
        raise EconomyError("A playlist de músicas está vazia.")
    return songs


def daily_song_index(user_id, song_count, today=None):
    if song_count < 1:
        raise ValueError("song_count must be positive")
    if today is None:
        today = datetime.now(DAILY_TIMEZONE).date()

    def index_for(day):
        key = f"{user_id}:{day.isoformat()}".encode("utf-8")
        digest = hashlib.blake2b(key, digest_size=8).digest()
        return int.from_bytes(digest, "big") % song_count

    index = index_for(today)
    if song_count > 1 and index == index_for(today - timedelta(days=1)):
        index = (index + 1) % song_count
    return index


def _normalized(text):
    return " ".join(text.casefold().split())


def _escape_lucene_phrase(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def select_release_group(results, song):
    expected_album = _normalized(song["album"] or song["title"])
    expected_artist = _normalized(song["artist"])
    matching_title = [
        item for item in results
        if _normalized(item.get("title", "")) == expected_album and item.get("id")
    ]
    if not matching_title:
        return results[0].get("id") if results else None

    for item in matching_title:
        artist_credit = item.get("artist-credit", [])
        credited_artists = {
            _normalized(
                credit.get("artist", {}).get("name", credit.get("name", ""))
            )
            for credit in artist_credit
            if isinstance(credit, dict)
        }
        if expected_artist in credited_artists:
            return item["id"]
    return matching_title[0]["id"]


def front_cover_url(cover_art):
    images = cover_art.get("images", [])
    front = next(
        (
            image for image in images
            if image.get("front") or "Front" in image.get("types", [])
        ),
        None,
    )
    if front is None:
        return None
    thumbnails = front.get("thumbnails", {})
    artwork_url = thumbnails.get("500") or thumbnails.get("large") or front.get("image")
    return artwork_url.replace("http://", "https://", 1) if artwork_url else None


class Music(commands.Cog):
    def __init__(self, bot, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.bot = bot
        self.clock = clock
        self.sleep = sleep
        self._musicbrainz_lock = asyncio.Lock()
        self._last_musicbrainz_request = float("-inf")
        self._cover_cache = {}

    async def _get_release_group(self, session, song):
        album = song["album"] or song["title"]
        query = (
            f'releasegroup:"{_escape_lucene_phrase(album)}" AND '
            f'artist:"{_escape_lucene_phrase(song["artist"])}"'
        )
        async with self._musicbrainz_lock:
            wait_seconds = 1 - (self.clock() - self._last_musicbrainz_request)
            if wait_seconds > 0:
                await self.sleep(wait_seconds)
            self._last_musicbrainz_request = self.clock()
            async with session.get(
                MUSICBRAINZ_SEARCH_URL,
                params={"query": query, "fmt": "json", "limit": 5},
            ) as response:
                response.raise_for_status()
                result = await response.json()
        return select_release_group(result.get("release-groups", []), song)

    async def lookup_album_art(self, song):
        cache_key = (_normalized(song["album"] or song["title"]), _normalized(song["artist"]))
        if cache_key in self._cover_cache:
            return self._cover_cache[cache_key]

        headers = {"User-Agent": USER_AGENT}
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                headers=headers,
            ) as session:
                release_group_id = await self._get_release_group(session, song)
                if release_group_id is None:
                    self._cover_cache[cache_key] = None
                    return None
                async with session.get(
                    COVER_ART_URL.format(mbid=release_group_id),
                    headers={"Accept": "application/json"},
                ) as response:
                    if response.status == 404:
                        self._cover_cache[cache_key] = None
                        return None
                    response.raise_for_status()
                    cover_art = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            log.warning(
                "Could not search MusicBrainz/Cover Art Archive for %s by %s",
                song["title"],
                song["artist"],
                exc_info=True,
            )
            raise EconomyError(
                "Não consegui pesquisar a capa do álbum agora. Tente novamente mais tarde."
            ) from error

        artwork_url = front_cover_url(cover_art)
        self._cover_cache[cache_key] = artwork_url
        return artwork_url

    @commands.command(
        cls=DualCommand,
        name="musica",
        aliases=["music", "song", "musica-do-dia"],
        help="Receba sua música do dia, escolhida da playlist e com a capa do álbum.",
    )
    async def musica(self, ctx):
        songs = load_playlist()
        song = songs[daily_song_index(ctx.author.id, len(songs))]
        artwork_url = await self.lookup_album_art(song)
        if artwork_url is None:
            raise EconomyError("Não encontrei a capa do álbum desta música no Cover Art Archive.")

        description = (
            f"{ctx.author.mention}, sua recomendação de hoje é **{song['title']}**."
        )
        if song["spotify_id"]:
            description += (
                f"\n[Ouvir no Spotify](https://open.spotify.com/track/{song['spotify_id']})"
            )
        embed = nextcord.Embed(
            title="🎵 Música do dia",
            description=description,
            color=0x77E5BC,
        )
        embed.add_field(name="Artista", value=song["artist"], inline=True)
        if song["album"]:
            embed.add_field(name="Álbum", value=song["album"], inline=True)
        embed.set_thumbnail(url=artwork_url)
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Music(bot))
