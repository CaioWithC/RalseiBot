"""Offline regressions for Discord delivery failures and Uno table lifecycle."""
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
import cogs.uno as uno_module

from cogs.uno import GameView, HandView, Table, Uno
from cogs.uno_rules import Card, RuleError, UnoGame
from db import Database


def missing_message():
    return nextcord.NotFound(SimpleNamespace(status=404, reason="Not Found"),
                            {"code": 10008, "message": "Unknown Message"})


class UnoRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_uno_window_starts_after_the_board_is_visible(self):
        self.table.game.uno_pending = {1: 3.0}

        async def delayed_upload(**kwargs):
            self.now = 4.0

        self.table.message.edit.side_effect = delayed_upload
        with patch.object(uno_module, "render_card", return_value=io.BytesIO(b"image")):
            await self.cog.publish(self.table, open_uno=[1])
        self.assertEqual(self.table.game.uno_pending[1], 7.0)
        self.assertFalse(self.table.view.children[2].disabled)
        self.assertTrue(self.table.view.children[3].disabled)

    async def test_timely_uno_click_survives_wait_for_network_response(self):
        self.table.game.hands[1] = [Card("single", "red", "2")]
        self.table.game.uno_pending = {1: 3.0}
        self.now = 2.0
        async def delay(**kwargs):
            self.now = 4.0
            interaction.response.is_done = lambda: True
        interaction = SimpleNamespace(user=SimpleNamespace(id=1),
            response=SimpleNamespace(is_done=lambda: False, defer=AsyncMock(side_effect=delay)),
            followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(uno_module, "render_card", return_value=io.BytesIO(b"image")):
            await self.cog.act(interaction, self.table, "call_uno")
        self.assertIn(1, self.table.game.uno_called)

    async def test_failed_public_update_during_expired_turn_refunds(self):
        self.now = self.table.game.turn_deadline
        self.table.message.edit.side_effect = missing_message()
        interaction = SimpleNamespace(user=SimpleNamespace(id=1),
            response=SimpleNamespace(is_done=lambda: True), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(uno_module, "render_card", return_value=io.BytesIO(b"image")):
            with self.assertRaises(nextcord.HTTPException):
                await self.cog.act(interaction, self.table, "draw")
        self.assertEqual(self.table.status, "cancelled")
        self.assertEqual([self.db.balance(player_id) for player_id in (1, 2, 3)], [100] * 3)
        self.assert_released()

    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        for player_id in (1, 2, 3):
            self.db.add_balance(player_id, 100)
        self.now = 0.0
        bot = SimpleNamespace(get_user=lambda player_id: SimpleNamespace(send=AsyncMock()))
        self.cog = Uno(bot, storage=self.db, clock=lambda: self.now)
        self.table = Table("recovery", 10, 20, 1, {1: "A", 2: "B", 3: "C"})
        self.table.game = UnoGame([1, 2, 3], now=self.now)
        self.table.status = "playing"
        self.table.message = SimpleNamespace(edit=AsyncMock())
        self.table.thread = SimpleNamespace(id=30, send=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())))
        self.table.view = GameView(self.cog, self.table)
        self.cog.tables[self.table.id] = self.table
        self.cog.memberships = {player_id: self.table.id for player_id in self.table.members}
        self.db.start_uno_game(self.table.id, [1, 2, 3], 10)

    async def asyncTearDown(self):
        self.cog.tick.cancel()
        if self.table.notification_task:
            self.table.notification_task.cancel()
        if self.table.view:
            self.table.view.stop()
        self.db.engine.dispose()

    def finish_engine(self):
        self.table.game.hands[1] = []
        self.table.game.players = [2, 3]
        self.table.game.winners = [1]
        self.table.game.finished = True

    def assert_paid_once(self):
        self.assertEqual([self.db.balance(player_id) for player_id in (1, 2, 3)], [155, 95, 95])

    def assert_released(self):
        self.assertNotIn(self.table.id, self.cog.tables)
        self.assertEqual(self.cog.memberships, {})

    async def test_uno_deadline_crossed_during_upload_is_corrected_by_timer(self):
        self.table.game.uno_pending = {1: 3.0}

        async def delayed_upload(**kwargs):
            self.now = 4.0

        self.table.message.edit.side_effect = delayed_upload
        with patch.object(uno_module, "render_card", return_value=io.BytesIO(b"image")):
            await self.cog.publish(self.table)
        self.assertFalse(self.table.view.children[2].disabled)
        self.assertTrue(self.table.view.children[3].disabled)
        await Uno.tick.coro(self.cog)
        self.assertTrue(self.table.view.children[2].disabled)
        self.assertFalse(self.table.view.children[3].disabled)
        self.assertEqual(self.table.message.edit.await_count, 2)

    async def test_uno_buttons_agree_with_engine_at_exact_deadline(self):
        self.table.game.uno_pending = {1: 3.0}
        self.now = 3.0
        view = GameView(self.cog, self.table)
        self.assertTrue(view.children[2].disabled)
        self.assertFalse(view.children[3].disabled)
        view.stop()

    async def test_final_render_failure_retries_without_paying_twice(self):
        self.finish_engine()
        with patch.object(uno_module, "render_card", side_effect=[RuntimeError("render interrupted"),
                                                       io.BytesIO(b"image")]) as renderer:
            with self.assertRaises(RuntimeError):
                await self.cog.publish(self.table)
            self.assertEqual(self.table.status, "finishing")
            self.assertIn(self.table.id, self.cog.tables)
            self.assert_paid_once()
            self.now = 4.0
            await Uno.tick.coro(self.cog)
            self.assertEqual(renderer.call_count, 1)
            self.now = 5.0
            await Uno.tick.coro(self.cog)
        self.assertEqual(self.table.status, "finished")
        self.assertEqual(self.table.receipt["status"], "settled")
        self.assert_paid_once()
        self.assert_released()
        self.table.message.edit.assert_awaited_once()

    async def test_deleted_final_board_posts_a_text_result_fallback(self):
        self.finish_engine()
        self.table.message.edit.side_effect = missing_message()
        with patch.object(uno_module, "render_card", return_value=io.BytesIO(b"image")):
            await self.cog.publish(self.table)
        self.table.thread.send.assert_awaited_once()
        embed = self.table.thread.send.await_args.kwargs["embed"]
        self.assertIsNone(embed.image.url)
        self.assertIn("+30", embed.description)
        self.assertEqual(self.table.status, "finished")
        self.assert_paid_once()
        self.assert_released()

    async def test_failed_edit_and_fallback_keep_result_for_later_delivery(self):
        self.finish_engine()
        self.table.message.edit.side_effect = [missing_message(), None]
        self.table.thread.send.side_effect = missing_message()
        with patch.object(uno_module, "render_card", side_effect=lambda *args, **kwargs: io.BytesIO(b"image")):
            with self.assertRaises(nextcord.HTTPException):
                await self.cog.publish(self.table)
            self.assertEqual(self.table.status, "finishing")
            self.assertIn(self.table.id, self.cog.tables)
            self.assert_paid_once()
            self.now = 5.0
            await Uno.tick.coro(self.cog)
        self.assertEqual(self.table.status, "finished")
        self.assert_paid_once()
        self.assert_released()

    async def test_refunded_receipt_cannot_be_announced_as_a_paid_win(self):
        self.finish_engine()
        self.db.cancel_uno_game(self.table.id)
        with patch.object(uno_module, "render_card", return_value=io.BytesIO(b"image")):
            await self.cog.publish(self.table)
        delivered = [call.kwargs.get("embed") for call in self.table.message.edit.await_args_list]
        delivered += [call.kwargs.get("embed") for call in self.table.thread.send.await_args_list]
        self.assertTrue(delivered)
        for embed in delivered:
            self.assertNotIn("+30", embed.description or "")
        self.assertEqual([self.db.balance(player_id) for player_id in (1, 2, 3)], [100] * 3)
        self.assert_released()

    async def test_private_delivery_error_does_not_cancel_active_game(self):
        view = HandView(self.cog, self.table, 1)
        interaction = SimpleNamespace(response=SimpleNamespace(is_done=lambda: True),
                                      followup=SimpleNamespace(send=AsyncMock()))
        with self.assertLogs("cogs.uno", level="ERROR"):
            await view.on_error(missing_message(), None, interaction)
        self.assertEqual(self.table.status, "playing")
        self.assertIn(self.table.id, self.cog.tables)
        self.assertEqual([self.db.balance(player_id) for player_id in (1, 2, 3)], [90] * 3)
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        view.stop()

    async def test_unload_refunds_and_invalidates_old_private_controls(self):
        view = HandView(self.cog, self.table, 1)
        interaction = SimpleNamespace(user=SimpleNamespace(id=1), guild=SimpleNamespace(id=10),
                                      response=SimpleNamespace(is_done=lambda: True),
                                      followup=SimpleNamespace(send=AsyncMock()))
        self.cog.cog_unload()
        self.assertFalse(await view.interaction_check(interaction))
        self.assertEqual([self.db.balance(player_id) for player_id in (1, 2, 3)], [100] * 3)
        self.assert_released()
        view.stop()

    async def test_unload_after_settlement_preserves_winnings(self):
        self.finish_engine()
        with patch.object(uno_module, "render_card", side_effect=RuntimeError("render interrupted")):
            with self.assertRaises(RuntimeError):
                await self.cog.publish(self.table)
        self.cog.cog_unload()
        self.assert_paid_once()
        self.assert_released()
        self.assertNotIn(self.table.status, ("lobby", "playing", "finishing"))


if __name__ == "__main__":
    unittest.main()
