"""Offline avatar loading and rendering checks."""
import asyncio
from io import BytesIO
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from PIL import Image
from cogs.leaderboard import Leaderboard, render_leaderboard


def portrait():
    output = BytesIO()
    Image.new("RGB", (80, 40), "#ff0000").save(output, format="PNG")
    return output.getvalue()


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncached_user_avatar_is_loaded(self):
        asset = SimpleNamespace(read=AsyncMock(return_value=portrait()))
        asset.with_size = lambda size: asset
        asset.with_static_format = lambda format: asset
        user = SimpleNamespace(display_name="Ralsei", display_avatar=asset)
        bot = SimpleNamespace(get_user=lambda _: None, fetch_user=AsyncMock(return_value=user))
        ctx = SimpleNamespace(guild=None, author=SimpleNamespace(id=42))
        entry = await Leaderboard(bot).ranking_entry(ctx, 1, "42", 100)
        self.assertEqual(entry, (1, "Ralsei", 100, True, portrait()))
        bot.fetch_user.assert_awaited_once_with(42)

    async def test_avatar_timeout_keeps_identity_and_fallback(self):
        asset = SimpleNamespace(read=AsyncMock(side_effect=asyncio.TimeoutError))
        asset.with_size = lambda size: asset
        asset.with_static_format = lambda format: asset
        member = SimpleNamespace(display_name="Ralsei", display_avatar=asset)
        bot = SimpleNamespace(get_user=lambda _: None)
        ctx = SimpleNamespace(guild=SimpleNamespace(get_member=lambda _: member),
                              author=SimpleNamespace(id=42))
        entry = await Leaderboard(bot).ranking_entry(ctx, 1, "42", 100)
        self.assertEqual(entry, (1, "Ralsei", 100, True, None))

    def test_portrait_is_drawn_and_circularly_clipped(self):
        with render_leaderboard([(1, "Ralsei", 100, False, portrait())], 1, 1, 1) as output:
            with Image.open(output) as image:
                self.assertEqual(image.getpixel((130, 241)), (255, 0, 0))
                self.assertEqual(image.getpixel((108, 219)), (25, 42, 52))

    def test_invalid_avatar_preserves_initial(self):
        with render_leaderboard([(1, "Ralsei", 100, False)], 1, 1, 1) as fallback:
            expected = fallback.getvalue()
        for avatar in (None, b"invalid image"):
            with render_leaderboard([(1, "Ralsei", 100, False, avatar)], 1, 1, 1) as output:
                self.assertEqual(output.getvalue(), expected)


if __name__ == "__main__":
    unittest.main()
