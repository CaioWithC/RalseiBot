"""Unit tests for the userinfo command, embeds, badges, and views."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import nextcord
from nextcord.ext import commands

from cogs.userinfo import _user_badges, _relative_time
from main import create_bot


class MockPublicFlags:
    def __init__(self, **flags):
        for k, v in flags.items():
            setattr(self, k, v)


class UserInfoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = create_bot()
        self.cog = self.bot.get_cog("UserInfo")
        self.dt = datetime(2024, 5, 17, 17, 1, tzinfo=timezone.utc)

    async def asyncTearDown(self):
        await self.bot.close()

    def test_relative_time_formatting(self):
        result = _relative_time(self.dt)
        ts = int(self.dt.timestamp())
        self.assertEqual(result, f"<t:{ts}:f> ( <t:{ts}:R> )")
        self.assertEqual(_relative_time(None), "Desconhecida")

    def test_user_badges_none(self):
        user = SimpleNamespace(public_flags=None, avatar=None)
        self.assertEqual(_user_badges(user), "Nenhuma")

    def test_user_badges_with_flags_and_nitro(self):
        flags = MockPublicFlags(hypesquad_bravery=True, active_developer=True)
        avatar = SimpleNamespace(is_animated=lambda: True)
        user = SimpleNamespace(public_flags=flags, avatar=avatar)
        badges = _user_badges(user)
        self.assertIn("bravery", badges)
        self.assertIn("activedev", badges)
        self.assertIn("nitro", badges)

    async def test_avatar_links_view_creates_buttons(self):
        from cogs.userinfo import AvatarLinksView
        avatar = SimpleNamespace(
            with_format=lambda fmt: SimpleNamespace(with_size=lambda s: SimpleNamespace(url=f"http://avatar.{fmt}")),
            is_animated=lambda: True,
        )
        user = SimpleNamespace(avatar=avatar, default_avatar=avatar)
        view = AvatarLinksView(user)
        labels = [btn.label for btn in view.children]
        self.assertIn("PNG", labels)
        self.assertIn("JPG", labels)
        self.assertIn("WebP", labels)
        self.assertIn("GIF", labels)

    async def test_userinfo_command_guild_member(self):
        author = SimpleNamespace(
            id=1241118323287261257,
            name="caio.withc.",
            display_name="caio' break even 26/10",
            accent_color=nextcord.Color(0x3B82F6),
            created_at=self.dt,
            joined_at=self.dt,
            display_avatar=SimpleNamespace(url="http://avatar.png", with_size=lambda s: SimpleNamespace(url="http://avatar256.png")),
            avatar=None,
            color=nextcord.Color(0xFF1493),
            top_role=SimpleNamespace(name="Caio", mention="<@&123>"),
            public_flags=MockPublicFlags(hypesquad_bravery=True),
        )

        guild = SimpleNamespace(
            get_member=lambda uid: author if uid == author.id else None,
            fetch_member=AsyncMock(return_value=author),
        )

        self.bot.fetch_user = AsyncMock(return_value=author)

        ctx = SimpleNamespace(
            author=author,
            guild=guild,
            send=AsyncMock(return_value=SimpleNamespace()),
        )

        await self.cog.userinfo(ctx)
        ctx.send.assert_awaited_once()
        kwargs = ctx.send.call_args.kwargs
        embeds = kwargs.get("embeds")
        self.assertIsNotNone(embeds)
        self.assertEqual(len(embeds), 2)

        # Check Embed 1: User info
        user_embed = embeds[0]
        self.assertEqual(user_embed.author.name, "Informações sobre o Usuário")
        self.assertEqual(user_embed.title, "caio' break even 26/10")
        self.assertEqual(user_embed.url, "https://discord.com/users/1241118323287261257")
        user_field_names = [f.name for f in user_embed.fields]
        self.assertIn("🏅 Insígnias", user_field_names)
        self.assertIn("🆔 ID do Discord", user_field_names)
        self.assertIn("🏷️ Tag do Discord", user_field_names)
        self.assertIn("📅 Data de Criação da Conta", user_field_names)

        # Check Embed 2: Member info
        member_embed = embeds[1]
        self.assertEqual(member_embed.author.name, "Informações sobre o Membro")
        self.assertEqual(member_embed.title, "caio' break even 26/10")
        member_field_names = [f.name for f in member_embed.fields]
        self.assertIn("📅 Data de Entrada no Servidor", member_field_names)
        self.assertIn("🏅 Maior cargo", member_field_names)

        # Check view buttons
        view = kwargs.get("view")
        self.assertEqual(view.__class__.__name__, "UserinfoView")
        button_labels = [btn.label for btn in view.children]
        self.assertIn("Ver o avatar global do usuário", button_labels)
        self.assertIn("Ver perfil", button_labels)


if __name__ == "__main__":
    unittest.main()

