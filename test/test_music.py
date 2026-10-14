"""Daily playlist recommendations and MusicBrainz cover art lookup."""
from datetime import date, timedelta
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from cogs.music import (
    COVER_ART_URL,
    MUSICBRAINZ_SEARCH_URL,
    Music,
    daily_song_index,
    front_cover_url,
    load_playlist,
    select_release_group,
)
from db import EconomyError


class MusicRecommendationTests(unittest.IsolatedAsyncioTestCase):
    def test_playlist_has_usable_music_records(self):
        songs = load_playlist()
        self.assertGreater(len(songs), 1)
        self.assertTrue(all(song["title"] and song["artist"] for song in songs))
        self.assertTrue(all(song["spotify_id"] for song in songs))

    def test_daily_song_is_personalized_stable_and_changes_each_day(self):
        songs = load_playlist()
        today = date(2026, 10, 13)
        today_indices = {
            user_id: daily_song_index(user_id, len(songs), today)
            for user_id in range(100)
        }
        self.assertGreater(len(set(today_indices.values())), 1)
        for user_id, index in today_indices.items():
            self.assertEqual(daily_song_index(user_id, len(songs), today), index)
            self.assertNotEqual(
                daily_song_index(user_id, len(songs), today + timedelta(days=1)),
                index,
            )

    def test_release_group_prefers_matching_album_and_artist(self):
        results = [
            {
                "id": "wrong-artist",
                "title": "Album",
                "artist-credit": [{"artist": {"name": "Another Artist"}}],
            },
            {
                "id": "matching-release-group",
                "title": "Album",
                "artist-credit": [{"artist": {"name": "The Artist"}}],
            },
        ]
        self.assertEqual(
            select_release_group(
                results,
                {"album": "Album", "artist": "The Artist", "title": "Track"},
            ),
            "matching-release-group",
        )

    def test_cover_archive_uses_front_image_thumbnail(self):
        self.assertEqual(
            front_cover_url({
                "images": [
                    {"front": False, "image": "https://example.com/back.jpg"},
                    {
                        "front": True,
                        "thumbnails": {"500": "https://example.com/cover-500.jpg"},
                    },
                ],
            }),
            "https://example.com/cover-500.jpg",
        )
        self.assertIsNone(front_cover_url({"images": []}))

    async def test_lookup_uses_musicbrainz_and_cover_art_archive_and_caches(self):
        song = {"title": "Track", "artist": "The Artist", "album": "Album"}
        responses = [
            {
                "release-groups": [{
                    "id": "matching-release-group",
                    "title": "Album",
                    "artist-credit": [{"artist": {"name": "The Artist"}}],
                }],
            },
            {
                "images": [{
                    "front": True,
                    "thumbnails": {"500": "https://example.com/cover-500.jpg"},
                }],
            },
        ]

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            def raise_for_status(self):
                return None

            async def json(self):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse(responses.pop(0))

        session = FakeSession()
        cog = Music(None)
        with patch("cogs.music.aiohttp.ClientSession", return_value=session):
            cover_url = await cog.lookup_album_art(song)
            cached_cover_url = await cog.lookup_album_art(song)

        self.assertEqual(cover_url, "https://example.com/cover-500.jpg")
        self.assertEqual(cached_cover_url, cover_url)
        self.assertEqual(
            [call[0] for call in session.calls],
            [MUSICBRAINZ_SEARCH_URL, COVER_ART_URL.format(mbid="matching-release-group")],
        )
        self.assertEqual(len(session.calls), 2)
        self.assertIn("releasegroup:", session.calls[0][1]["params"]["query"])
        self.assertIn("artist:", session.calls[0][1]["params"]["query"])

    async def test_music_command_sends_song_and_cover_in_embed(self):
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=123, mention="<@123>"),
            send=AsyncMock(),
        )
        cog = Music(None)
        song = {
            "title": "Track",
            "artist": "The Artist",
            "album": "Album",
            "spotify_id": "spotify-track-id",
        }
        with (
            patch("cogs.music.load_playlist", return_value=[song]),
            patch.object(
                cog,
                "lookup_album_art",
                new=AsyncMock(return_value="https://example.com/cover.jpg"),
            ),
        ):
            await Music.musica.callback(cog, ctx)

        embed = ctx.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "🎵 Música do dia")
        self.assertEqual(embed.thumbnail.url, "https://example.com/cover.jpg")
        self.assertEqual(embed.fields[0].name, "Artista")
        self.assertIn("open.spotify.com/track/spotify-track-id", embed.description)

    async def test_missing_cover_art_still_sends_song_without_thumbnail(self):
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=123, mention="<@123>"),
            send=AsyncMock(),
        )
        cog = Music(None)
        with (
            patch("cogs.music.load_playlist", return_value=[{
                "title": "Track",
                "artist": "The Artist",
                "album": "Album",
                "spotify_id": "",
            }]),
            patch.object(cog, "lookup_album_art", new=AsyncMock(return_value=None)),
        ):
            await Music.musica.callback(cog, ctx)

        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "🎵 Música do dia")
        self.assertIsNone(embed.thumbnail.url)
        self.assertNotIn("view", ctx.send.call_args.kwargs)

    async def test_lookup_falls_back_to_google_search_when_musicbrainz_has_no_cover(self):
        song = {"title": "Track", "artist": "The Artist", "album": "Album", "spotify_id": ""}
        cog = Music(None)

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            def raise_for_status(self):
                return None

            async def json(self):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                return FakeResponse({"release-groups": []})

        session = FakeSession()
        with (
            patch("cogs.music.aiohttp.ClientSession", return_value=session),
            patch.object(
                cog,
                "search_google_image",
                new=AsyncMock(return_value="https://example.com/google-cover.jpg"),
            ) as mock_google,
        ):
            cover_url = await cog.lookup_album_art(song)

        self.assertEqual(cover_url, "https://example.com/google-cover.jpg")
        mock_google.assert_awaited_once_with(session, "Album", "The Artist", song)

    async def test_search_google_image_extracts_image_url(self):
        cog = Music(None)

        class FakeHtmlResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def text(self):
                return '<html><body><script>["https://example.com/art.jpg", 500, 500]</script></body></html>'

        class FakeSession:
            def get(self, url, **kwargs):
                return FakeHtmlResponse()

        img_url = await cog.search_google_image(FakeSession(), "Album", "The Artist")
        self.assertEqual(img_url, "https://example.com/art.jpg")

    async def test_admmusica_changes_author_song_when_no_member_specified(self):
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=123, mention="<@123>", bot=False),
            send=AsyncMock(),
        )
        cog = Music(None, overrides_path=None)
        songs = [
            {"title": "Track 1", "artist": "Artist 1", "album": "Album 1", "spotify_id": ""},
            {"title": "Track 2", "artist": "Artist 2", "album": "Album 2", "spotify_id": ""},
        ]
        with (
            patch("cogs.music.load_playlist", return_value=songs),
            patch.object(cog, "lookup_album_art", new=AsyncMock(return_value=None)),
        ):
            await Music.admmusica.callback(cog, ctx, member=None)

        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "🎵 Música do dia alterada")
        self.assertIn("sua música do dia foi alterada", embed.description)
        new_song = cog.get_user_song(123, songs)
        self.assertIn(new_song, songs)

    async def test_admmusica_changes_mentioned_member_song(self):
        author = SimpleNamespace(id=123, mention="<@123>", bot=False)
        target = SimpleNamespace(id=456, mention="<@456>", bot=False)
        ctx = SimpleNamespace(author=author, send=AsyncMock())
        cog = Music(None, overrides_path=None)
        songs = [
            {"title": "Track A", "artist": "Artist A", "album": "Album A", "spotify_id": ""},
            {"title": "Track B", "artist": "Artist B", "album": "Album B", "spotify_id": ""},
        ]
        with (
            patch("cogs.music.load_playlist", return_value=songs),
            patch.object(cog, "lookup_album_art", new=AsyncMock(return_value=None)),
        ):
            await Music.admmusica.callback(cog, ctx, member=target)

        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "🎵 Música do dia alterada")
        self.assertIn("<@456>", embed.description)
        self.assertIn("por <@123>", embed.description)
        new_song = cog.get_user_song(456, songs)
        self.assertIn(new_song, songs)

    async def test_admmusica_sets_specific_song_by_name(self):
        target = SimpleNamespace(id=456, mention="<@456>", bot=False)
        ctx = SimpleNamespace(author=SimpleNamespace(id=123, mention="<@123>", bot=False), send=AsyncMock())
        cog = Music(None, overrides_path=None)
        songs = [
            {"title": "Alpha", "artist": "Singer", "album": "First", "spotify_id": ""},
            {"title": "Beta Special", "artist": "Singer", "album": "Second", "spotify_id": ""},
        ]
        with (
            patch("cogs.music.load_playlist", return_value=songs),
            patch.object(cog, "lookup_album_art", new=AsyncMock(return_value=None)),
        ):
            await Music.admmusica.callback(cog, ctx, member=target, musica="Beta Special")

        new_song = cog.get_user_song(456, songs)
        self.assertEqual(new_song["title"], "Beta Special")

    async def test_admmusica_rejects_bots(self):
        bot_target = SimpleNamespace(id=999, mention="<@999>", bot=True)
        ctx = SimpleNamespace(author=SimpleNamespace(id=123, mention="<@123>", bot=False), send=AsyncMock())
        cog = Music(None, overrides_path=None)
        with patch("cogs.music.load_playlist", return_value=[{"title": "A", "artist": "B", "album": "C", "spotify_id": ""}]):
            with self.assertRaises(EconomyError):
                await Music.admmusica.callback(cog, ctx, member=bot_target)

    def test_music_override_expires_on_next_day(self):
        cog = Music(None, overrides_path=None)
        songs = [
            {"title": "Song 0", "artist": "A", "album": "X", "spotify_id": ""},
            {"title": "Song 1", "artist": "B", "album": "Y", "spotify_id": ""},
        ]
        day1 = date(2026, 10, 13)
        day2 = date(2026, 10, 14)
        cog.set_user_song(123, 1, today=day1)
        self.assertEqual(cog.get_user_song(123, songs, today=day1)["title"], "Song 1")
        # On day2, override must expire and revert to day2 daily song
        expected_default = songs[daily_song_index(123, len(songs), today=day2)]
        self.assertEqual(cog.get_user_song(123, songs, today=day2), expected_default)


if __name__ == "__main__":
    unittest.main()


