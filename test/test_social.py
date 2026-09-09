"""Profile command integration, upload validation, rendering and persistence."""
import asyncio
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from PIL import Image
import nextcord
from nextcord.ext import commands
from db import Database, EconomyError
from main import create_bot
from social import (normalize_background, parse_color, render_profile,
                    text_color, MAX_UPLOAD_BYTES, WIDTH, HEIGHT)


def png(color="blue", size=(320, 240)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def user(user_id, name="Ralsei", avatar=None):
    asset = SimpleNamespace(read=AsyncMock(return_value=avatar or png("white")))
    asset.with_size = lambda size: asset
    asset.with_static_format = lambda fmt: asset
    return SimpleNamespace(id=user_id, display_name=name, display_avatar=asset)


class ProfileStorageTests(unittest.TestCase):
    def test_settings_survive_restart_and_do_not_change_balances(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + (Path(directory) / "social.db").as_posix()
            db = Database(url)
            try:
                db.add_balance(1, 500)
                db.add_balance(2, 1000)
                image = normalize_background(png())
                db.update_profile(1, color="#ABCDEF", about="Olá!", background=image)
                db.engine.dispose()
                db = Database(url)
                profile = db.profile(1)
                self.assertEqual((profile["color"], profile["about"], profile["background"]),
                                 ("#ABCDEF", "Olá!", image))
                self.assertEqual((profile["balance"], profile["rank"]), (500, 2))
                self.assertEqual(db.profile(2)["about"], "")
                db.update_profile(1, background=None)
                self.assertIsNone(db.profile(1)["background"])
                self.assertEqual(db.profile(1)["color"], "#ABCDEF")
                self.assertEqual(db.balance(1), 500)
            finally:
                db.engine.dispose()

    def test_rank_matches_rich_list_including_ties_and_new_users(self):
        db = Database("sqlite:///:memory:")
        try:
            for user_id, balance in (("30", 300), ("2", 100), ("10", 100)):
                db.add_balance(user_id, balance)
            rows, total = db.leaderboard()
            for rank, (user_id, balance) in enumerate(rows, start=1):
                self.assertEqual(db.profile(user_id)["rank"], rank)
            self.assertEqual(db.profile(99)["rank"], 4)
            self.assertEqual(db.profile(99)["balance"], 0)
            db.add_balance(99, 1000)
            self.assertEqual(db.profile(99)["rank"], 1)
        finally:
            db.engine.dispose()


class ProfileImageTests(unittest.TestCase):
    def test_hex_validation_and_readable_text(self):
        self.assertEqual(parse_color(" #aBc123 "), "#ABC123")
        self.assertEqual(parse_color("77e5bc"), "#77E5BC")
        for value in ("#123", "red", "#GGFFFF", "##123456", "#12345678", "", "FF FF FF"):
            with self.assertRaises(EconomyError):
                parse_color(value)
        self.assertEqual(text_color("#FFFFFF"), "#000000")
        self.assertEqual(text_color("#000000"), "#FFFFFF")

    def test_background_normalization_and_invalid_uploads(self):
        normalized = normalize_background(png("blue", (100, 300)))
        with Image.open(BytesIO(normalized)) as image:
            self.assertEqual(image.size, (1000, 400))
            self.assertEqual(image.format, "JPEG")
        for data in (b"not an image", b"", b"x" * (MAX_UPLOAD_BYTES + 1)):
            with self.assertRaises(EconomyError):
                normalize_background(data)
        # This highly compressible image is small in bytes but excessive when decoded.
        with self.assertRaises(EconomyError):
            normalize_background(png(size=(4001, 4000)))

    def test_layout_background_avatar_and_extreme_text(self):
        profile = {"discord_id": "123456789012345678", "balance": 9_000_000_000_000_000,
                   "rank": 12345, "color": "#FFFFFF", "about": "W" * 300,
                   "background": normalize_background(png("blue"))}
        with render_profile(profile, "Ralsei 💚 " * 30, png("red")) as output:
            with Image.open(output) as image:
                self.assertEqual(image.size, (WIDTH, HEIGHT))
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(image.getpixel((99, 96)), (255, 0, 0))
                self.assertGreater(image.getpixel((500, 350))[2], 250)
        profile.update(color="#000000", about="\n" * 299, background=None)
        with render_profile(profile, "", b"invalid avatar") as output:
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                image.verify()


class SocialCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.bot = create_bot()
        self.bot._connection.user = SimpleNamespace(id=999)
        self.cog = self.bot.get_cog("Social")
        self.cog.storage = self.db
        self.author = user(111111111111111111)
        self.seconds = 0

    async def asyncTearDown(self):
        await self.bot.close()
        self.db.engine.dispose()

    async def context(self, content, attachments=(), author=None):
        self.seconds += 6
        message = SimpleNamespace(content=content, author=author or self.author, guild=None,
                                  channel=SimpleNamespace(id=123), attachments=list(attachments),
                                  edited_at=None, created_at=datetime.fromtimestamp(
                                      1_800_000_000 + self.seconds, timezone.utc), _state=self.bot._connection)
        ctx = await self.bot.get_context(message)
        ctx.send = AsyncMock()
        return ctx

    async def invoke(self, content, **kwargs):
        ctx = await self.context(content, **kwargs)
        self.assertIsNotNone(ctx.command)
        await ctx.command.invoke(ctx)
        return ctx

    async def test_group_routes_color_bio_and_profile_png(self):
        await self.invoke("r.perfil cor #77e5bc")
        await self.invoke("r.profile about Gosto de aventuras e de fazer amigos!")
        profile = self.db.profile(self.author.id)
        self.assertEqual(profile["color"], "#77E5BC")
        self.assertEqual(profile["about"], "Gosto de aventuras e de fazer amigos!")
        ctx = await self.context("r.profile")
        sent = []

        async def capture(**kwargs):
            sent.append(kwargs["file"].fp.read())
        ctx.send.side_effect = capture
        await ctx.command.invoke(ctx)
        self.assertEqual(ctx.send.call_args.kwargs["file"].filename, "profile.png")
        with Image.open(BytesIO(sent[0])) as image:
            self.assertEqual(image.size, (1000, 790))
        self.author.display_avatar.read.assert_awaited_once()
        await self.invoke("r.perfil sobremim reset")
        self.assertEqual(self.db.profile(self.author.id)["about"], "")

    async def test_background_upload_persists_and_reset_removes(self):
        attachment = SimpleNamespace(size=1000, read=AsyncMock(return_value=png("orange")))
        await self.invoke("r.profile background", attachments=[attachment])
        stored = self.db.profile(self.author.id)["background"]
        self.assertIsNotNone(stored)
        with Image.open(BytesIO(stored)) as image:
            self.assertEqual(image.size, (1000, 400))
        await self.invoke("r.perfil fundo reset")
        self.assertIsNone(self.db.profile(self.author.id)["background"])

    async def test_invalid_edits_preserve_existing_settings(self):
        self.db.update_profile(self.author.id, color="#112233", about="Original", background=normalize_background(png()))
        original = self.db.profile(self.author.id)
        invalid = SimpleNamespace(size=10, read=AsyncMock(return_value=b"bad image"))
        too_big = SimpleNamespace(size=MAX_UPLOAD_BYTES + 1, read=AsyncMock())
        for content, attachments in (("r.profile color bad", []), ("r.profile about " + "x" * 301, []),
                                     ("r.profile background", []), ("r.profile background", [invalid]),
                                     ("r.profile background", [too_big]), ("r.profile background https://example.com", [])):
            with self.subTest(content=content[:50]):
                with self.assertRaises(commands.CommandInvokeError) as caught:
                    await self.invoke(content, attachments=attachments)
                self.assertIsInstance(caught.exception.original, EconomyError)
                self.assertEqual(self.db.profile(self.author.id), original)
        too_big.read.assert_not_awaited()

    async def test_other_profile_and_owner_scoped_settings(self):
        other = nextcord.User(state=self.bot._connection, data={
            "id": "222222222222222222", "username": "Kris", "discriminator": "0", "avatar": None})
        self.db.add_balance(other.id, 2000)
        self.db.update_profile(other.id, about="Kris bio", color="#123456")
        with patch.object(self.bot, "get_user", return_value=other), \
                patch.object(nextcord.Asset, "read", new=AsyncMock(return_value=png())) as read:
            ctx = await self.invoke(f"r.profile <@{other.id}>")
            read.assert_awaited_once()
        self.assertEqual(ctx.send.call_args.kwargs["file"].filename, "profile.png")
        await self.invoke("r.profile color #ABCDEF")
        self.assertEqual(self.db.profile(other.id)["color"], "#123456")
        self.assertEqual(self.db.profile(self.author.id)["color"], "#ABCDEF")

    async def test_avatar_timeout_falls_back_and_upload_timeout_preserves_background(self):
        self.author.display_avatar.read.side_effect = asyncio.TimeoutError
        ctx = await self.invoke("r.profile")
        ctx.send.assert_awaited_once()
        attachment = SimpleNamespace(size=100, read=AsyncMock(side_effect=asyncio.TimeoutError))
        with self.assertRaises(commands.CommandInvokeError) as caught:
            await self.invoke("r.profile background", attachments=[attachment])
        self.assertIsInstance(caught.exception.original, EconomyError)
        self.assertIsNone(self.db.profile(self.author.id)["background"])


if __name__ == "__main__":
    unittest.main()
