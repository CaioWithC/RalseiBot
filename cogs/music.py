import asyncio
import csv
import hashlib
import json
import logging
import os
import random
import re
import ssl
import time
import typing
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
import nextcord
from nextcord.ext import commands

from cogs.command_support import DualCommand
from db import DAILY_TIMEZONE, EconomyError

try:
    import certifi
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = None

log = logging.getLogger(__name__)
PLAYLIST_PATH = Path(__file__).resolve().parent.parent / "assets" / "playlist.csv"
OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "assets" / "music_overrides.json"
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/release-group/"
COVER_ART_URL = "https://coverartarchive.org/release-group/{mbid}"
USER_AGENT = "RalseiBot/1.0 (https://github.com/CaioWithC/RalseiBot)"


GOOGLE_SEARCH_IMAGE_URL = "https://www.google.com/search"


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
    def __init__(self, bot, *, clock=time.monotonic, sleep=asyncio.sleep, overrides_path=None):
        self.bot = bot
        self.clock = clock
        self.sleep = sleep
        self._musicbrainz_lock = asyncio.Lock()
        self._last_musicbrainz_request = float("-inf")
        self._cover_cache = {}
        self._overrides_path = Path(overrides_path) if overrides_path else OVERRIDES_PATH
        self._song_overrides = {}
        self._load_overrides()

    def _load_overrides(self):
        try:
            if self._overrides_path and self._overrides_path.exists():
                with open(self._overrides_path, "r", encoding="utf-8") as f:
                    self._song_overrides = json.load(f)
        except Exception as error:
            log.warning("Could not load music overrides: %s", error)
            self._song_overrides = {}

    def _save_overrides(self):
        if not self._overrides_path:
            return
        try:
            self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._overrides_path, "w", encoding="utf-8") as f:
                json.dump(self._song_overrides, f, indent=2)
        except Exception as error:
            log.warning("Could not save music overrides: %s", error)

    def get_user_song(self, user_id, songs, today=None):
        if today is None:
            today = datetime.now(DAILY_TIMEZONE).date()
        today_str = today.isoformat()
        override = self._song_overrides.get(str(user_id))
        if override and override.get("date") == today_str:
            idx = override.get("index")
            if isinstance(idx, int) and 0 <= idx < len(songs):
                return songs[idx]
        return songs[daily_song_index(user_id, len(songs), today)]

    def set_user_song(self, user_id, song_index, today=None):
        if today is None:
            today = datetime.now(DAILY_TIMEZONE).date()
        today_str = today.isoformat()
        self._song_overrides = {
            uid: data for uid, data in self._song_overrides.items()
            if data.get("date") == today_str
        }
        self._song_overrides[str(user_id)] = {
            "date": today_str,
            "index": song_index,
        }
        self._save_overrides()

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

    async def search_google_image(self, session, album, artist, song=None):
        query = f"{album} {artist} album cover".strip()

        # 1. Google Custom Search JSON API (if configured in environment)
        api_key = os.getenv("GOOGLE_API_KEY")
        cse_id = os.getenv("GOOGLE_CSE_ID") or os.getenv("GOOGLE_SEARCH_CX")
        if api_key and cse_id:
            try:
                params = {
                    "q": query,
                    "searchType": "image",
                    "num": 1,
                    "key": api_key,
                    "cx": cse_id,
                }
                async with session.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = data.get("items", [])
                        if items and "link" in items[0]:
                            return items[0]["link"]
            except Exception as error:
                log.warning("Google Custom Search API error for %s: %s", query, error)

        # 2. Google Images search scraping
        try:
            params = {"q": query, "tbm": "isch"}
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            async with session.get(
                GOOGLE_SEARCH_IMAGE_URL,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    matches = re.findall(
                        r'\["(https?://[^\s"]+?\.(?:jpg|jpeg|png|webp))"', text
                    )
                    valid = [
                        u for u in matches
                        if "gstatic.com" not in u and "google.com" not in u
                    ]
                    if valid:
                        return valid[0]

                    tbn_matches = re.findall(
                        r'(https://encrypted-tbn0\.gstatic\.com/images\?q=tbn:[^"\'\s&;]+)',
                        text,
                    )
                    if tbn_matches:
                        return tbn_matches[0]
        except Exception as error:
            log.warning("Google Images search failed for %s: %s", query, error)

        # 3. Fallback: Spotify oEmbed if spotify_id is available
        if song and song.get("spotify_id"):
            try:
                spot_url = f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{song['spotify_id']}"
                async with session.get(spot_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if data.get("thumbnail_url"):
                            return data["thumbnail_url"]
            except Exception:
                pass

        # 4. Fallback: iTunes Search API
        try:
            itunes_url = "https://itunes.apple.com/search"
            itunes_params = {
                "term": f"{album} {artist}",
                "media": "music",
                "entity": "album",
                "limit": 1,
            }
            async with session.get(
                itunes_url,
                params=itunes_params,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    results = data.get("results", [])
                    if results and "artworkUrl100" in results[0]:
                        return results[0]["artworkUrl100"].replace("100x100bb", "600x600bb")
        except Exception:
            pass

        return None

    async def lookup_album_art(self, song):
        album = song["album"] or song["title"]
        artist = song["artist"]
        cache_key = (_normalized(album), _normalized(artist))
        if cache_key in self._cover_cache:
            return self._cover_cache[cache_key]

        headers = {"User-Agent": USER_AGENT}
        artwork_url = None
        connector = aiohttp.TCPConnector(ssl=SSL_CONTEXT) if SSL_CONTEXT else None
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=10),
                headers=headers,
            ) as session:
                try:
                    release_group_id = await self._get_release_group(session, song)
                    if release_group_id is not None:
                        async with session.get(
                            COVER_ART_URL.format(mbid=release_group_id),
                            headers={"Accept": "application/json"},
                        ) as response:
                            if response.status == 200:
                                cover_art = await response.json()
                                artwork_url = front_cover_url(cover_art)
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    log.warning(
                        "Could not search MusicBrainz/Cover Art Archive for %s by %s",
                        song["title"],
                        song["artist"],
                        exc_info=True,
                    )

                if artwork_url is None:
                    artwork_url = await self.search_google_image(session, album, artist, song)
        except Exception:
            log.warning(
                "Could not lookup album art for %s by %s",
                song["title"],
                song["artist"],
                exc_info=True,
            )

        self._cover_cache[cache_key] = artwork_url
        return artwork_url

    async def _send_song_embed(self, ctx, song, *, title, description):
        try:
            artwork_url = await self.lookup_album_art(song)
        except Exception:
            log.warning("Falha ao buscar capa do álbum para %s", song["title"], exc_info=True)
            artwork_url = None

        view = None
        if song["spotify_id"]:
            spotify_url = f"https://open.spotify.com/track/{song['spotify_id']}"
            description += f"\n[Ouvir no Spotify]({spotify_url})"
            view = nextcord.ui.View()
            view.add_item(
                nextcord.ui.Button(label="Ouvir no Spotify", url=spotify_url)
            )

        embed = nextcord.Embed(
            title=title,
            description=description,
            color=0x77E5BC,
        )
        embed.add_field(name="Artista", value=song["artist"], inline=True)
        if song["album"]:
            embed.add_field(name="Álbum", value=song["album"], inline=True)
        if artwork_url:
            embed.set_thumbnail(url=artwork_url)

        kwargs = {"embed": embed}
        if view is not None:
            kwargs["view"] = view
        await ctx.send(**kwargs)

    @commands.command(
        cls=DualCommand,
        name="musica",
        aliases=["music", "song", "musica-do-dia"],
        help="Receba sua música do dia, escolhida da playlist e com a capa do álbum.",
    )
    async def musica(self, ctx):
        songs = load_playlist()
        song = self.get_user_song(ctx.author.id, songs)
        description = (
            f"{ctx.author.mention}, sua recomendação de hoje é **{song['title']}**."
        )
        await self._send_song_embed(
            ctx,
            song,
            title="🎵 Música do dia",
            description=description,
        )

    @commands.command(
        cls=DualCommand,
        name="admmusica",
        aliases=["setmusica", "trocarmusica", "trocamusica"],
        help="Administrador: troca a música do dia de uma pessoa (marcando-a) ou a sua própria: r.admmusica [@membro] [música].",
    )
    @commands.has_permissions(administrator=True)
    async def admmusica(
        self,
        ctx,
        member: typing.Optional[nextcord.Member] = None,
        *,
        musica: str = None,
    ):
        target = member or ctx.author
        if getattr(target, "bot", False):
            raise EconomyError("Bots não têm recomendação diária de música.")

        songs = load_playlist()
        current_song = self.get_user_song(target.id, songs)

        if musica:
            query = _normalized(musica)
            matches = [
                (i, s) for i, s in enumerate(songs)
                if query in _normalized(s["title"])
                or query in _normalized(s["artist"])
                or query in _normalized(s["album"])
            ]
            if not matches:
                raise EconomyError(
                    f"Não encontrei nenhuma música na playlist correspondente a '{musica}'."
                )
            exact = [
                (i, s) for i, s in matches
                if _normalized(s["title"]) == query or _normalized(s["album"]) == query
            ]
            new_index, song = exact[0] if exact else matches[0]
        else:
            candidates = [
                (i, s) for i, s in enumerate(songs)
                if _normalized(s["title"]) != _normalized(current_song["title"])
                or _normalized(s["artist"]) != _normalized(current_song["artist"])
            ]
            if not candidates:
                candidates = list(enumerate(songs))
            new_index, song = random.choice(candidates)

        self.set_user_song(target.id, new_index)

        if target.id == ctx.author.id:
            description = (
                f"{ctx.author.mention}, sua música do dia foi alterada para **{song['title']}**."
            )
        else:
            description = (
                f"A música do dia de {target.mention} foi alterada para **{song['title']}** por {ctx.author.mention}."
            )

        await self._send_song_embed(
            ctx,
            song,
            title="🎵 Música do dia alterada",
            description=description,
        )

def setup(bot):
    bot.add_cog(Music(bot))
