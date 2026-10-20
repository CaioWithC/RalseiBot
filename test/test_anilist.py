"""Unit tests for the AniList profile lookup and card generator."""
import asyncio
from io import BytesIO
import unittest
from unittest.mock import AsyncMock, patch

import nextcord
from PIL import Image

from cogs.anilist import (
    ANILIST_COLOR,
    fetch_anilist_data,
    get_genre_color,
    render_anilist_overview,
    AniList,
)
from db import EconomyError, database
from main import create_bot


class AniListTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = create_bot()
        self.cog = self.bot.get_cog("AniList")
        self.test_user_id = 999999999999999999

    async def asyncTearDown(self):
        await self.bot.close()

    def test_genre_color_mapping(self):
        self.assertEqual(get_genre_color("Slice of Life"), "#55d836")
        self.assertEqual(get_genre_color("Comedy"), "#02a9ff")
        self.assertEqual(get_genre_color("Romance"), "#9256f3")
        self.assertEqual(get_genre_color("Psychological"), "#f779a4")
        self.assertEqual(get_genre_color("Drama"), "#e85d75")
        # Fallback for unknown genre
        self.assertTrue(get_genre_color("Unknown Genre").startswith("#"))

    def test_render_overview_with_covers_and_genres(self):
        # Create dummy covers
        a1 = Image.new("RGBA", (100, 150), (255, 0, 0, 255))
        a2 = Image.new("RGBA", (100, 150), (0, 255, 0, 255))
        m1 = Image.new("RGBA", (100, 150), (0, 0, 255, 255))
        genres = [
            {"genre": "Slice of Life", "count": 9},
            {"genre": "Comedy", "count": 6},
            {"genre": "Romance", "count": 6},
            {"genre": "Psychological", "count": 2},
            {"genre": "Drama", "count": 2},
        ]
        out = render_anilist_overview([a1, a2], [m1], genres)
        self.assertIsInstance(out, BytesIO)
        img = Image.open(out)
        self.assertEqual(img.width, 490)
        self.assertGreater(img.height, 500)

    def test_render_overview_empty(self):
        out = render_anilist_overview([], [], [])
        self.assertIsInstance(out, BytesIO)
        img = Image.open(out)
        self.assertEqual(img.width, 490)

    def test_db_anilist_link_and_unlink(self):
        # Link anilist account
        database.update_profile(self.test_user_id, anilist="CaioWithC")
        data = database.profile(self.test_user_id)
        self.assertEqual(data.get("anilist"), "CaioWithC")

        # Unlink anilist account
        database.update_profile(self.test_user_id, anilist=None)
        data = database.profile(self.test_user_id)
        self.assertIsNone(data.get("anilist"))

    @patch("cogs.anilist.download_covers")
    @patch("cogs.anilist.fetch_anilist_data")
    async def test_anilist_command_success(self, mock_fetch, mock_download):
        mock_fetch.return_value = {
            "name": "CaioWithC",
            "siteUrl": "https://anilist.co/user/CaioWithC",
            "avatar": {"large": "https://example.com/avatar.jpg"},
            "statistics": {
                "anime": {
                    "count": 9,
                    "minutesWatched": 2016,  # 1.4 days
                    "meanScore": 80.0,
                    "genres": [{"genre": "Slice of Life", "count": 9}],
                }
            },
            "favourites": {
                "anime": {"nodes": []},
                "manga": {"nodes": []},
            },
        }
        mock_download.return_value = []

        ctx = AsyncMock()
        ctx.author.id = self.test_user_id

        await self.cog.anilist.callback(self.cog, ctx, usuario="CaioWithC")

        ctx.send.assert_called_once()
        _, kwargs = ctx.send.call_args
        embed = kwargs.get("embed")
        self.assertIsNotNone(embed)
        self.assertEqual(embed.title, "AniList")
        self.assertEqual(embed.url, "https://anilist.co/user/CaioWithC")
        self.assertEqual(embed.color.value, ANILIST_COLOR)
        self.assertIn("**Nome: CaioWithC**", embed.description)
        self.assertIn("Total Anime: 9", embed.description)
        self.assertIn("Days Watched: 1.4", embed.description)
        self.assertIn("Mean Score: 80.0", embed.description)
        self.assertEqual(embed.thumbnail.url, "https://example.com/avatar.jpg")
        self.assertIn("file", kwargs)

    @patch("cogs.anilist.fetch_anilist_data")
    async def test_anilist_command_link_action(self, mock_fetch):
        mock_fetch.return_value = {
            "name": "CaioWithC",
            "siteUrl": "https://anilist.co/user/CaioWithC",
            "avatar": {"large": "https://example.com/avatar.jpg"},
            "statistics": {
                "anime": {
                    "count": 9,
                    "minutesWatched": 2016,
                    "meanScore": 80.0,
                    "genres": [],
                }
            },
            "favourites": {"anime": {"nodes": []}, "manga": {"nodes": []}},
        }
        ctx = AsyncMock()
        ctx.author.id = self.test_user_id

        # Use r.anilist set CaioWithC
        await self.cog.anilist.callback(self.cog, ctx, usuario="set CaioWithC")
        data = database.profile(self.test_user_id)
        self.assertEqual(data.get("anilist"), "CaioWithC")

        # Cleanup
        database.update_profile(self.test_user_id, anilist=None)

    async def test_anilist_command_unlink_when_not_linked(self):
        ctx = AsyncMock()
        ctx.author.id = self.test_user_id
        database.update_profile(self.test_user_id, anilist=None)

        with self.assertRaises(EconomyError) as cm:
            await self.cog.anilist.callback(self.cog, ctx, usuario="unlink")
        self.assertIn("não possui uma conta", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

