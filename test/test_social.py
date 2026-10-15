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
from cogs.social import (normalize_background, parse_color, render_profile,
                    text_color, MAX_UPLOAD_BYTES, WIDTH, HEIGHT,
                    get_available_pets, ProfileView, PetSelectView, PetDropdown)


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
                db.update_profile(1, pet="txt/BAMGEUT.png")
                self.assertEqual(db.profile(1)["pet"], "txt/BAMGEUT.png")
                db.update_profile(1, pet=None)
                self.assertIsNone(db.profile(1)["pet"])
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

    def test_render_with_pet_and_missing_pet_fallback(self):
        profile = {"discord_id": "123456789012345678", "balance": 1000,
                   "rank": 1, "color": "#101C24", "about": "Bio com pet",
                   "background": None, "pet": "txt/BAMGEUT.png"}
        with render_profile(profile, "User") as output:
            with Image.open(output) as img:
                self.assertEqual(img.size, (WIDTH, HEIGHT))
                self.assertEqual(img.format, "PNG")
        # Missing pet key should not raise an error
        profile["pet"] = "nonexistent/pet.png"
        with render_profile(profile, "User") as output:
            with Image.open(output) as img:
                self.assertEqual(img.size, (WIDTH, HEIGHT))
                self.assertEqual(img.format, "PNG")


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

    async def test_profile_command_attaches_profile_view_with_button(self):
        ctx = await self.invoke("r.profile")
        view = ctx.send.call_args.kwargs.get("view")
        self.assertEqual(type(view).__name__, "ProfileView")
        self.assertTrue(any(getattr(item, "label", None) in {"Trocar Pet", "Escolher Pet"} for item in view.children))

    async def test_pet_command_routes_selection_and_reset(self):
        await self.invoke("r.profile pet bamgeut")
        self.assertEqual(self.db.profile(self.author.id)["pet"], "txt/BAMGEUT.png")
        await self.invoke("r.profile pet reset")
        self.assertIsNone(self.db.profile(self.author.id)["pet"])

    async def test_pet_command_without_args_sends_select_view(self):
        ctx = await self.invoke("r.profile pet")
        view = ctx.send.call_args.kwargs.get("view")
        self.assertEqual(type(view).__name__, "PetSelectView")

    async def test_pet_dropdown_updates_profile(self):
        parent_view = ProfileView(self.cog, self.author, self.author.id)
        parent_msg = AsyncMock()
        parent_view.message = parent_msg

        select_view = PetSelectView(self.cog, self.author, parent_view=parent_view)
        dropdown = select_view.children[0]
        self.assertEqual(type(dropdown).__name__, "PetDropdown")

        # Test selection
        interaction = SimpleNamespace(
            user=self.author,
            response=SimpleNamespace(
                edit_message=AsyncMock(),
                send_message=AsyncMock(),
            )
        )
        dropdown._selected_values = ["txt/BAMGEUT.png"]
        await dropdown.callback(interaction)
        self.assertEqual(self.db.profile(self.author.id)["pet"], "txt/BAMGEUT.png")
        interaction.response.edit_message.assert_awaited_once()
        parent_msg.edit.assert_awaited_once()

        # Test unauthorized interaction
        stranger = user(999999999999999999)
        unauth_interaction = SimpleNamespace(
            user=stranger,
            response=SimpleNamespace(
                send_message=AsyncMock(),
                edit_message=AsyncMock(),
            )
        )
        dropdown._selected_values = ["none"]
        await dropdown.callback(unauth_interaction)
        self.assertEqual(self.db.profile(self.author.id)["pet"], "txt/BAMGEUT.png")
        unauth_interaction.response.send_message.assert_awaited_once()

    async def test_choose_pet_button_authorized_opens_select_view_with_custom_id(self):
        parent_view = ProfileView(self.cog, self.author, self.author.id)
        mock_msg = SimpleNamespace(id=111222)
        interaction = SimpleNamespace(
            user=self.author,
            message=mock_msg,
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        button = next(item for item in parent_view.children if getattr(item, "label", None) in {"Trocar Pet", "Escolher Pet"})
        await button.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        self.assertTrue(kwargs.get("ephemeral"))
        select_view = kwargs.get("view")
        self.assertIsInstance(select_view, PetSelectView)
        dropdown = select_view.children[0]
        self.assertTrue(dropdown.custom_id and dropdown.custom_id is not ...)
        components = select_view.to_components()
        self.assertIn("custom_id", components[0]["components"][0])

    async def test_choose_pet_button_unauthorized_is_rejected(self):
        parent_view = ProfileView(self.cog, self.author, self.author.id)
        stranger = user(999999999999999999)
        interaction = SimpleNamespace(
            user=stranger,
            message=SimpleNamespace(id=111222),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        button = next(item for item in parent_view.children if getattr(item, "label", None) in {"Trocar Pet", "Escolher Pet"})
        await button.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.call_args.kwargs
        self.assertTrue(kwargs.get("ephemeral"))
        self.assertIn("Apenas o dono deste perfil", interaction.response.send_message.call_args.args[0])
        self.assertIsNone(kwargs.get("view"))

    async def test_namemc_command_links_and_shows_embed(self):
        fake_profile = {
            "username": "CaioWithC",
            "uuid": "742c4cf2-1a77-44eb-b40c-9a0a94c6d0ba",
            "raw_id": "742c4cf21a7744ebb40c9a0a94c6d0ba",
            "date_str": "03/01/2021",
            "timestamp": 1609697268,
        }
        with patch("cogs.social.fetch_minecraft_profile", AsyncMock(return_value=fake_profile)):
            ctx = await self.invoke("r.namemc CaioWithC")
            self.assertEqual(self.db.profile(self.author.id)["namemc"], "CaioWithC")
            embed = ctx.send.call_args.kwargs.get("embed")
            self.assertIsNotNone(embed)
            self.assertEqual(embed.title, "Nome: CaioWithC")
            self.assertIn("Idade da conta: 03/01/2021 (<t:1609697268:R>)", embed.description)
            self.assertIn("[NameMC](https://namemc.com/profile/CaioWithC)", embed.description)
            self.assertIn("-# uuid: ||742c4cf2-1a77-44eb-b40c-9a0a94c6d0ba||", embed.description)
            self.assertEqual(embed.color.value, 0xBE6C72)
            self.assertEqual(embed.thumbnail.url, "https://mc-heads.net/avatar/742c4cf21a7744ebb40c9a0a94c6d0ba")

    async def test_namemc_command_view_own_linked_account(self):
        self.db.update_profile(self.author.id, namemc="CaioWithC")
        fake_profile = {
            "username": "CaioWithC",
            "uuid": "742c4cf2-1a77-44eb-b40c-9a0a94c6d0ba",
            "raw_id": "742c4cf21a7744ebb40c9a0a94c6d0ba",
            "date_str": "03/01/2021",
            "timestamp": 1609697268,
        }
        with patch("cogs.social.fetch_minecraft_profile", AsyncMock(return_value=fake_profile)):
            ctx = await self.invoke("r.namemc")
            embed = ctx.send.call_args.kwargs.get("embed")
            self.assertIsNotNone(embed)
            self.assertEqual(embed.title, "Nome: CaioWithC")

    async def test_namemc_command_not_linked_raises_error(self):
        with self.assertRaises(commands.CommandInvokeError) as caught:
            await self.invoke("r.namemc")
        self.assertIsInstance(caught.exception.original, EconomyError)
        self.assertIn("Você ainda não vinculou", str(caught.exception.original))

    async def test_namemc_command_desvincular(self):
        self.db.update_profile(self.author.id, namemc="CaioWithC")
        ctx = await self.invoke("r.namemc desvincular")
        self.assertIsNone(self.db.profile(self.author.id)["namemc"])
        self.assertIn("desvinculada com sucesso", ctx.send.call_args.args[0])

    async def test_namemc_command_view_other_member(self):
        other = user(222222222222222222)
        self.db.update_profile(other.id, namemc="Notch")
        fake_profile = {
            "username": "Notch",
            "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
            "raw_id": "069a79f444e94726a5befca90e38aaf5",
            "date_str": "31/05/2021",
            "timestamp": 1622432499,
        }
        with patch("cogs.social.fetch_minecraft_profile", AsyncMock(return_value=fake_profile)):
            ctx = await self.invoke(f"r.namemc <@{other.id}>")
            embed = ctx.send.call_args.kwargs.get("embed")
            self.assertIsNotNone(embed)
            self.assertEqual(embed.title, "Nome: Notch")

    async def test_namemc_command_not_found_raises_error(self):
        with patch("cogs.social.fetch_minecraft_profile", AsyncMock(return_value=None)):
            with self.assertRaises(commands.CommandInvokeError) as caught:
                await self.invoke("r.namemc invalidplayer")
            self.assertIsInstance(caught.exception.original, EconomyError)
            self.assertIn("Conta do Minecraft não encontrada", str(caught.exception.original))


if __name__ == "__main__":
    unittest.main()
