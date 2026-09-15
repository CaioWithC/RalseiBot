"""Offline moderation checks with real command parsing and temporary storage."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
from nextcord.ext import commands

from cogs.command_support import InteractionContext
from cogs.moderation import LOCK_FLAGS, Moderation, ModerationError, parse_duration
from db import Database
from main import create_bot, error_message


class ModerationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "moderation.db").as_posix()
        self.db = Database(self.url)
        self.bot = create_bot()
        self.bot._connection.user = SimpleNamespace(id=999)
        self.cog = self.bot.get_cog("Moderation")
        self.cog.storage = self.db
        self.guild = SimpleNamespace(id=123, owner_id=1, default_role=Mock(),
                                     ban=AsyncMock(), unban=AsyncMock())
        self.author = self.member(2, 5)
        self.target = self.member(3, 2)
        self.guild.me = self.member(999, 10)
        self.channel = Mock(spec=nextcord.TextChannel)
        self.channel.id = 456
        self.channel.guild = self.guild
        self.channel.mention = "<#456>"
        self.channel.permissions_for.side_effect = lambda member: member.guild_permissions
        self.overwrite = nextcord.PermissionOverwrite(view_channel=False, send_messages=True,
                                                       create_private_threads=False)
        self.channel.overwrites_for.side_effect = lambda _: nextcord.PermissionOverwrite.from_pair(*self.overwrite.pair())

        async def set_permissions(role, *, overwrite, reason):
            self.overwrite = overwrite or nextcord.PermissionOverwrite()

        self.channel.set_permissions = AsyncMock(side_effect=set_permissions)
        self.channel.edit = AsyncMock()
        self.channel.purge = AsyncMock(return_value=[Mock(), Mock()])
        self.guild.fetch_channel = AsyncMock(return_value=self.channel)

    def member(self, user_id, role):
        return SimpleNamespace(id=user_id, top_role=role, guild=self.guild, bot=False, display_name=f"Member {user_id}",
                               guild_permissions=nextcord.Permissions.all(),
                               timeout=AsyncMock(), kick=AsyncMock())

    async def asyncTearDown(self):
        await self.bot.close()
        self.db.engine.dispose()
        self.directory.cleanup()

    async def context(self, content):
        message = SimpleNamespace(content=content, author=self.author, guild=self.guild,
                                  channel=self.channel, attachments=[], edited_at=None,
                                  created_at=datetime.now(timezone.utc), id=123456789012345678,
                                  _state=self.bot._connection)
        ctx = await self.bot.get_context(message)
        ctx.send = AsyncMock()
        return ctx

    async def invoke(self, content):
        ctx = await self.context(content)
        with patch.object(commands.MemberConverter, "convert", new=AsyncMock(return_value=self.target)):
            await ctx.command.invoke(ctx)
        return ctx

    def test_duration_bounds(self):
        for value, seconds in (("30s", 30), ("10m", 600), ("2H", 7200), ("28d", 2419200)):
            self.assertEqual(parse_duration(value), timedelta(seconds=seconds))
        for value in ("0s", "29d", "-1h", "1.5h", "10", "1h30m", "9" * 5000 + "d"):
            with self.assertRaises(ModerationError):
                parse_duration(value)

    async def test_member_actions_and_audit_reason(self):
        await self.invoke("r.banir <@3> spam repetido")
        self.guild.ban.assert_awaited_once_with(self.target, reason="Moderador: 2 | spam repetido", delete_message_seconds=0)
        await self.invoke("r.expulsar <@3> ofensas")
        self.target.kick.assert_awaited_once_with(reason="Moderador: 2 | ofensas")
        self.target.guild_permissions = nextcord.Permissions.none()
        before = nextcord.utils.utcnow()
        await self.invoke("r.timeout <@3> 10m spam")
        until = self.target.timeout.call_args.args[0]
        self.assertTrue(before + timedelta(minutes=10) <= until <= nextcord.utils.utcnow() + timedelta(minutes=10))
        await self.invoke("r.desmutar <@3>")
        self.assertIsNone(self.target.timeout.call_args.args[0])
        await self.invoke("r.desbanir 123456789012345678 recurso aceito")
        self.assertEqual(self.guild.unban.call_args.args[0].id, 123456789012345678)

    async def test_hierarchy_self_owner_and_bot_are_protected(self):
        for user_id, target_role, actor_role, bot_role in (
            (2, 2, 5, 10), (999, 2, 5, 10), (1, 2, 5, 10),
            (3, 5, 5, 10), (3, 6, 5, 10), (3, 5, 6, 5),
        ):
            self.target.id, self.target.top_role = user_id, target_role
            self.author.top_role, self.guild.me.top_role = actor_role, bot_role
            for action in ("ban", "kick", "unmute"):
                with self.assertRaises(ModerationError):
                    await self.invoke(f"r.{action} <@3>")
        self.guild.ban.assert_not_awaited()
        self.target.kick.assert_not_awaited()
        self.target.timeout.assert_not_awaited()

    async def test_owner_can_moderate_higher_role_but_bot_still_needs_hierarchy(self):
        self.author.id = self.guild.owner_id
        self.target.top_role = 7
        await self.invoke("r.kick <@3>")
        self.target.top_role = 10
        with self.assertRaises(ModerationError):
            await self.invoke("r.kick <@3>")
        self.target.kick.assert_awaited_once()

    async def test_runtime_permissions_and_dm_guard(self):
        for command, permission in (("ban", "ban_members"), ("kick", "kick_members"),
                                    ("mute", "moderate_members"), ("unmute", "moderate_members"),
                                    ("unban", "ban_members")):
            ctx = await self.context("r." + command)
            self.author.guild_permissions = nextcord.Permissions.none()
            with self.assertRaises(commands.MissingPermissions):
                await ctx.command.can_run(ctx)
            self.author.guild_permissions = nextcord.Permissions(**{permission: True})
            self.guild.me.guild_permissions = nextcord.Permissions.none()
            with self.assertRaises(commands.BotMissingPermissions):
                await ctx.command.can_run(ctx)
            self.guild.me.guild_permissions = nextcord.Permissions.all()
            self.assertTrue(await ctx.command.can_run(ctx))
        for name in ("ban", "kick", "mute", "unmute", "unban", "lock", "unlock", "clear", "slowmode"):
            ctx = await self.context("r." + name)
            ctx.guild = None
            with self.assertRaises(commands.NoPrivateMessage):
                await ctx.command.can_run(ctx)

    async def test_timeout_rejects_admins_and_bots(self):
        for bot, admin in ((False, True), (True, False)):
            self.target.bot = bot
            self.target.guild_permissions = nextcord.Permissions(administrator=admin)
            with self.assertRaises(ModerationError):
                await self.invoke("r.mute <@3> 10m")
        self.target.timeout.assert_not_awaited()

    async def test_lock_restores_tristate_permissions_after_restart(self):
        original = {flag: getattr(self.overwrite, flag) for flag in LOCK_FLAGS}
        await self.invoke("r.lock")
        self.assertTrue(all(getattr(self.overwrite, flag) is False for flag in LOCK_FLAGS))
        self.assertFalse(self.overwrite.view_channel)
        self.db.engine.dispose()
        self.db = Database(self.url)
        replacement = Moderation(self.bot, self.db)
        # Preserve an unrelated permission changed by an administrator while locked.
        self.overwrite.attach_files = False
        ctx = await self.context("r.unlock")
        await replacement.change_lock(ctx, None, None, unlock=True)
        self.assertEqual({flag: getattr(self.overwrite, flag) for flag in LOCK_FLAGS}, original)
        self.assertFalse(self.overwrite.attach_files)
        self.assertFalse(self.overwrite.view_channel)
        self.assertIsNone(self.db.channel_lock(self.guild.id, self.channel.id))

    async def test_concurrent_locks_do_not_replace_original_snapshot(self):
        ctx = await self.context("r.lock")
        results = await asyncio.gather(*(self.cog.change_lock(ctx, None, None, unlock=False) for _ in range(2)),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(result, ModerationError) for result in results), 1)
        self.channel.set_permissions.assert_awaited_once()
        self.assertTrue(self.db.channel_lock(self.guild.id, self.channel.id)["send_messages"])

    async def test_unlock_without_snapshot_never_grants_access(self):
        with self.assertRaises(ModerationError):
            await self.invoke("r.unlock")
        self.channel.set_permissions.assert_not_awaited()

    async def test_lock_failure_cleanup_and_unlock_failure_retains_snapshot(self):
        forbidden = nextcord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions")
        side_effect = self.channel.set_permissions.side_effect
        self.channel.set_permissions.side_effect = forbidden
        with self.assertRaises(commands.CommandInvokeError):
            await self.invoke("r.lock")
        self.assertIsNone(self.db.channel_lock(self.guild.id, self.channel.id))
        self.channel.set_permissions.side_effect = side_effect
        await self.invoke("r.lock")
        self.channel.set_permissions.side_effect = forbidden
        with self.assertRaises(commands.CommandInvokeError):
            await self.invoke("r.unlock")
        self.assertIsNotNone(self.db.channel_lock(self.guild.id, self.channel.id))

    async def test_permissions_are_checked_in_selected_channel(self):
        ctx = await self.context("r.lock")
        target = Mock(spec=nextcord.TextChannel)
        target.guild = self.guild
        target.permissions_for.return_value = nextcord.Permissions.none()
        with self.assertRaises(commands.MissingPermissions):
            await self.cog.change_lock(ctx, target, None, unlock=False)
        target.set_permissions.assert_not_called()
        self.channel.permissions_for.side_effect = lambda member: (
            nextcord.Permissions.none() if member.id == 999 else nextcord.Permissions.all())
        with self.assertRaises(commands.BotMissingPermissions):
            await self.invoke("r.clear 10")
        self.channel.purge.assert_not_awaited()

    async def test_clear_boundaries_and_slowmode_limits(self):
        ctx = await self.invoke("r.limpar 2")
        self.channel.purge.assert_awaited_once_with(limit=2, before=ctx.message)
        for text in ("r.clear 0", "r.clear 101", "r.slowmode -1", "r.slowmode 21601"):
            with self.assertRaises(ModerationError):
                await self.invoke(text)
        await self.invoke("r.modolento 0")
        self.assertEqual(self.channel.edit.call_args.kwargs["slowmode_delay"], 0)

    async def test_slash_uses_original_checks_and_clear_excludes_deferred_response(self):
        apps = {app.name: app for app in self.bot.get_all_application_commands()}
        for name in ("ban", "kick", "mute", "unmute", "unban", "lock", "unlock", "clear", "slowmode"):
            self.assertEqual(apps[name].get_payload(None)["contexts"], [0])
            self.assertNotEqual(apps[name].get_payload(None)["default_member_permissions"], "0")
        interaction = SimpleNamespace(id=123456789012345678, user=self.author, guild=self.guild,
                                      channel=self.channel, created_at=nextcord.utils.utcnow(),
                                      followup=SimpleNamespace(send=AsyncMock()))
        ctx = InteractionContext(self.bot, interaction, self.bot.get_command("clear"), {"amount": 2})
        await ctx.command.invoke(ctx)
        self.channel.purge.assert_awaited_once_with(limit=2, before=interaction.created_at)
        self.author.guild_permissions = nextcord.Permissions.none()
        ctx = InteractionContext(self.bot, interaction, self.bot.get_command("ban"), {"member": self.target})
        with self.assertRaises(commands.MissingPermissions):
            await ctx.command.invoke(ctx)
        self.guild.ban.assert_not_awaited()

    async def test_unban_missing_user_and_validation(self):
        self.guild.unban.side_effect = nextcord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Ban")
        with self.assertRaises(ModerationError) as raised:
            await self.invoke("r.unban 123456789012345678")
        self.assertIn("não está banido", error_message(raised.exception, "r.unban"))
        self.guild.unban.reset_mock()
        for text in ("r.unban abc", "r.unban 99999999999999999999", "r.ban <@3> " + "x" * 401):
            with self.assertRaises(ModerationError):
                await self.invoke(text)
        self.guild.unban.assert_not_awaited()
        self.guild.ban.assert_not_awaited()

    async def test_all_slash_options_reach_the_moderation_actions(self):
        apps = {app.name: app for app in self.bot.get_all_application_commands()}
        self.target.guild_permissions = nextcord.Permissions.none()
        cases = (
            ("ban", {"member": "3", "reason": "spam"}),
            ("kick", {"member": "3"}),
            ("mute", {"member": "3", "duration": "10m"}),
            ("unmute", {"member": "3"}),
            ("unban", {"user_id": "123456789012345678"}),
            ("lock", {"channel": "456"}),
            ("unlock", {"channel": "456"}),
            ("slowmode", {"seconds": 15, "channel": "456", "reason": "chat movimentado"}),
            ("clear", {"amount": 2}),
        )
        for name, values in cases:
            with self.subTest(command=name):
                app = apps[name]
                received = asyncio.Event()
                response = SimpleNamespace(defer=AsyncMock(), is_done=lambda: True)

                async def send(content=None, **kwargs):
                    received.set()

                interaction = SimpleNamespace(
                    id=123456789012345678, user=self.author, guild=self.guild, channel=self.channel, client=self.bot,
                    application_command=app,
                    created_at=nextcord.utils.utcnow(), response=response,
                    followup=SimpleNamespace(send=AsyncMock(side_effect=send)),
                    data={"options": [{"name": key, "value": value, "type": app.options[key].type.value}
                                      for key, value in values.items()]},
                    _resolve_users=lambda: [self.target], _set_application_command=lambda command: None,
                )
                with patch.object(self.bot._connection, "get_channel", return_value=self.channel):
                    await app.call(self.bot._connection, interaction)
                    await asyncio.wait_for(received.wait(), timeout=3)
                response.defer.assert_awaited_once()
                self.assertNotIn("ephemeral", interaction.followup.send.call_args.kwargs)
        self.guild.ban.assert_awaited_once()
        self.target.kick.assert_awaited_once()
        self.assertEqual(self.target.timeout.await_count, 2)
        self.guild.unban.assert_awaited_once()
        self.assertEqual(self.channel.set_permissions.await_count, 2)
        self.channel.edit.assert_awaited_once_with(slowmode_delay=15, reason="Moderador: 2 | chat movimentado")
        self.channel.purge.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
