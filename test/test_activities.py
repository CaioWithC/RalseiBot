"""Presence scheduling tests with a fake clock and no Discord connection."""
import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord

from activities import Activities, ACTIVITIES, ADMIN_REACTION_SECONDS, MANUAL_ACTIVITY_SECONDS
from db import EconomyError


class ActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1000.0
        self.guild = SimpleNamespace(name="Reino do Caio", member_count=123, unavailable=False)
        self.bot = SimpleNamespace(
            guilds=[self.guild], latency=0.042, walk_commands=lambda: iter(range(18)),
            change_presence=AsyncMock(), is_ready=Mock(return_value=True), is_closed=Mock(return_value=False),
        )
        self.cog = Activities(self.bot, clock=lambda: self.now)

    async def asyncTearDown(self):
        self.cog.cog_unload()
        task = self.cog.update_activity.get_task()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    def context(self, name="ping", *, admin=True, guild=True, failed=False):
        return SimpleNamespace(
            command=SimpleNamespace(qualified_name=name), command_failed=failed,
            guild=self.guild if guild else None,
            author=SimpleNamespace(display_name="Caio", guild_permissions=nextcord.Permissions(administrator=admin)),
            send=AsyncMock(),
        )

    async def test_rotation_contains_praise_live_stats_and_valid_custom_activity_payloads(self):
        self.cog.completed_commands = 7
        texts = []
        for _ in ACTIVITIES:
            await self.cog.refresh()
            activity = self.bot.change_presence.call_args.kwargs["activity"]
            self.assertIsInstance(activity, nextcord.CustomActivity)
            payload = activity.to_dict()
            self.assertEqual(set(payload), {"name", "state", "type"})
            self.assertEqual(payload["type"], 4)
            self.assertEqual(payload["name"], "Custom Status")
            self.assertLessEqual(len(payload["state"]), 128)
            texts.append(payload["state"])
            self.now += 60
        self.assertGreaterEqual(sum("Caio" in text for text in texts), 5)
        combined = "\n".join(texts)
        for expected in ("18 comandos", "123 membros", "42 ms", "7 comandos concluídos", "r.help", "/help"):
            self.assertIn(expected, combined)
        await self.cog.refresh()
        self.assertEqual(self.cog.current_text, texts[0])

    async def test_rotation_waits_a_minute_and_does_not_resend_unchanged_text(self):
        await self.cog.refresh()
        first = self.cog.current_text
        for seconds in (5, 10, 30, 59):
            self.now = 1000 + seconds
            await self.cog.refresh()
        self.bot.change_presence.assert_awaited_once()
        self.now = 1060
        await self.cog.refresh()
        self.assertNotEqual(first, self.cog.current_text)
        self.assertEqual(self.bot.change_presence.await_count, 2)

    async def test_server_stats_handle_changes_missing_counts_and_reconnect_latency(self):
        self.cog.rotation_index = 3
        self.assertIn("123 membros", self.cog.rotation_text())
        self.guild.member_count = 124
        self.assertIn("124 membros", self.cog.rotation_text())
        self.guild.member_count = None
        self.assertIn("Cuidando de Reino do Caio", self.cog.rotation_text())
        self.guild.unavailable = True
        self.assertIn("Esperando novos amigos", self.cog.rotation_text())
        self.bot.guilds = []
        self.bot.latency = float("nan")
        self.cog.rotation_index = next(index for index, text in enumerate(ACTIVITIES) if "{latency}" in text)
        self.assertIn("conectando", self.cog.rotation_text())
        self.bot.guilds = [SimpleNamespace(name="X" * 100, member_count=10, unavailable=False),
                           SimpleNamespace(name="Outro reino", member_count=20, unavailable=False)]
        self.cog.rotation_index = 3
        self.assertLessEqual(len(self.cog.rotation_text()), 128)
        self.cog.rotation_index = len(ACTIVITIES) + 3
        self.assertIn("Outro reino: 20 membros", self.cog.rotation_text())

    async def test_only_successful_admin_commands_create_reactions(self):
        for ctx in (self.context(admin=False), self.context(guild=False), self.context(failed=True)):
            await self.cog.on_command_completion(ctx)
            self.assertIsNone(self.cog.override)
        self.assertEqual(self.cog.completed_commands, 2)
        await self.cog.on_command_completion(self.context("addbalance"))
        self.assertIn("Caio distribuiu DarkMoney", self.cog.override.text)
        await self.cog.refresh()
        self.assertIn("Caio distribuiu DarkMoney", self.cog.current_text)
        self.now += ADMIN_REACTION_SECONDS
        await self.cog.refresh()
        self.assertIsNone(self.cog.override)
        self.assertIn("meu dono", self.cog.current_text)

    async def test_bursts_keep_latest_reaction_and_limit_presence_updates(self):
        sent_at = []

        async def capture(**kwargs):
            sent_at.append(self.now)

        self.bot.change_presence.side_effect = capture
        for second in range(61):
            self.now = 1000 + second
            ctx = self.context("ping")
            ctx.author.display_name = f"Admin {second}"
            await self.cog.on_command_completion(ctx)
            await self.cog.refresh()
        self.assertIn("Admin 60", self.cog.current_text)
        for previous, current in zip(sent_at, sent_at[1:]):
            self.assertGreaterEqual(current - previous, 10)
        self.assertEqual(len(sent_at), 7)

    async def test_manual_activity_has_priority_then_rotation_resumes(self):
        ctx = self.context("activity")
        await self.cog.activity.callback(self.cog, ctx, text="  Evento no reino!\nVamos jogar.  ")
        await self.cog.on_command_completion(ctx)
        await self.cog.on_command_completion(self.context("pay"))
        await self.cog.refresh()
        self.assertEqual(self.cog.current_text, "Evento no reino! Vamos jogar.")
        self.assertTrue(self.cog.override.manual)
        self.now += MANUAL_ACTIVITY_SECONDS - 1
        await self.cog.refresh()
        self.bot.change_presence.assert_awaited_once()
        self.now += 1
        await self.cog.refresh()
        self.assertIsNone(self.cog.override)
        self.assertIn("meu dono", self.cog.current_text)

    async def test_reset_clears_pending_manual_and_admin_reactions(self):
        ctx = self.context("activity")
        for manual in (True, False):
            if manual:
                await self.cog.activity.callback(self.cog, ctx, text="Manutenção breve")
            else:
                await self.cog.on_command_completion(self.context("rich"))
            await self.cog.activity.callback(self.cog, ctx, text=" RESET ")
            await self.cog.on_command_completion(ctx)
            self.assertIsNone(self.cog.override)
        await self.cog.refresh()
        self.assertIn("Caio", self.cog.current_text)

    async def test_invalid_manual_activity_preserves_existing_override(self):
        ctx = self.context("activity")
        await self.cog.activity.callback(self.cog, ctx, text="Feliz aniversário, Caio!")
        original = self.cog.override
        for text in ("  \n  ", "x" * 129):
            with self.assertRaises(EconomyError):
                await self.cog.activity.callback(self.cog, ctx, text=text)
            self.assertIs(self.cog.override, original)
        await self.cog.activity.callback(self.cog, ctx, text="x" * 128)
        self.assertEqual(len(self.cog.override.text), 128)

    async def test_transport_failure_retries_without_losing_pending_activity(self):
        self.bot.change_presence.side_effect = [OSError("disconnected"), None]
        with self.assertLogs("activities", level="WARNING"):
            await self.cog.refresh()
        self.assertIsNone(self.cog.current_text)
        self.assertEqual(self.cog.rotation_index, 0)
        self.now += 5
        await self.cog.refresh()
        self.bot.change_presence.assert_awaited_once()
        self.now += 5
        await self.cog.refresh()
        self.assertIn("Caio", self.cog.current_text)
        self.assertEqual(self.cog.rotation_index, 1)

    async def test_worker_waits_for_ready_and_stops_when_closed(self):
        self.bot.is_ready.return_value = False
        await self.cog.refresh()
        self.bot.is_ready.return_value = True
        self.bot.is_closed.return_value = True
        await self.cog.refresh()
        self.bot.change_presence.assert_not_awaited()

    async def test_ready_starts_one_worker_and_reconnect_restores_manual_status(self):
        sent = asyncio.Event()
        self.bot.change_presence.side_effect = lambda **kwargs: sent.set()
        await self.cog.activity.callback(self.cog, self.context("activity"), text="Caio é incrível!")
        await self.cog.on_ready()
        first_task = self.cog.update_activity.get_task()
        await self.cog.on_ready()
        self.assertIs(first_task, self.cog.update_activity.get_task())
        await asyncio.wait_for(sent.wait(), timeout=1)
        self.bot.change_presence.assert_awaited_once()
        await self.cog.on_ready()
        self.now += 10
        await self.cog.refresh()
        self.assertEqual(self.bot.change_presence.await_count, 2)
        self.assertEqual(self.cog.current_text, "Caio é incrível!")
        self.cog.cog_unload()
        with self.assertRaises(asyncio.CancelledError):
            await first_task
        self.assertFalse(self.cog.update_activity.is_running())


if __name__ == "__main__":
    unittest.main()
