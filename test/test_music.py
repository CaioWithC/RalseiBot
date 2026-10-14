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


if __name__ == "__main__":
    unittest.main()

