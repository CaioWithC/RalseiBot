"""Offline regressions for moving Uno boards and private turn notifications."""
import asyncio
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord

from cogs.uno import GameView, HandView, Table, Uno
from cogs.uno_rules import Card
from db import Database


def forbidden():
    return nextcord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Cannot send messages")


class UnoActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.now = 1000.0
        self.message_id = 100
        self.guild = SimpleNamespace(id=10, me=object())
        self.users = {uid: SimpleNamespace(id=uid, bot=False, display_name=f"Jogador {uid}", send=AsyncMock())
                      for uid in (1, 2, 3)}
        self.bot = SimpleNamespace(get_user=Mock(side_effect=self.users.get), fetch_user=AsyncMock())
        self.cog = Uno(self.bot, storage=self.db, clock=lambda: self.now)
        self.thread = Mock(spec=nextcord.Thread)
        self.thread.id, self.thread.guild, self.thread.mention = 51, self.guild, "<#51>"
        self.thread.send = AsyncMock(side_effect=lambda **kwargs: self.board())
        invite = SimpleNamespace(edit=AsyncMock(), create_thread=AsyncMock(return_value=self.thread))
        channel = Mock(spec=nextcord.TextChannel)
        channel.id, channel.guild = 50, self.guild
        channel.permissions_for.return_value = nextcord.Permissions.all()
        channel.send = AsyncMock(return_value=invite)
        self.table = await self.cog.create_table(channel, self.users[1])
        await self.cog.lobby_action(self.table, self.users[2], "join")
        self.renderer = patch("cogs.uno.render_card", side_effect=lambda *args, **kwargs: io.BytesIO(b"image"))
        self.renderer.start()
        self.addCleanup(self.renderer.stop)

    async def asyncTearDown(self):
        self.cog.cog_unload()
        await asyncio.sleep(0)
        self.db.engine.dispose()

    def next_id(self):
        self.message_id += 1
        return self.message_id

    def board(self):
        return SimpleNamespace(id=self.next_id(), edit=AsyncMock(), delete=AsyncMock())

    def chat_message(self, *, channel=None, author=None):
        return SimpleNamespace(id=self.next_id(), guild=self.guild,
                               channel=self.thread if channel is None else channel,
                               author=self.users[3] if author is None else author)

    async def chat(self, count):
        for _ in range(count):
            await self.cog.on_message(self.chat_message())

    async def start(self):
        await self.cog.lobby_action(self.table, self.users[1], "start")
        await self.table.notification_task

    def interaction(self, player_id):
        return SimpleNamespace(user=self.users[player_id], response=SimpleNamespace(is_done=lambda: True),
                               followup=SimpleNamespace(send=AsyncMock()))

    def set_cards(self, *, value="3"):
        game = self.table.game
        game.hands[game.current_player] = [Card("play", "red", value), Card("keep", "blue", "4")]
        game.discard_pile = [Card("top", "red", "5")]
        game.current_color = "red"

    async def test_lobby_moves_on_each_tenth_message_and_edits_do_not_reset_count(self):
        original, old_view = self.table.message, self.table.view
        await self.chat(9)
        self.thread.send.assert_awaited_once()
        await self.cog.refresh_lobby(self.table)
        await self.chat(1)
        self.assertEqual(self.thread.send.await_count, 2)
        self.assertIsNot(self.table.message, original)
        original.delete.assert_awaited_once()
        self.assertTrue(old_view.is_finished())
        self.assertEqual(self.table.message_count, 0)
        second = self.table.message
        await self.chat(10)
        self.assertEqual(self.thread.send.await_count, 3)
        second.delete.assert_awaited_once()
        await self.cog.refresh_lobby(self.table)
        self.table.message.edit.assert_awaited_once()
        self.users[1].send.assert_not_awaited()

    async def test_playing_board_moves_with_image_controls_and_unchanged_turn(self):
        await self.start()
        self.set_cards()
        self.table.deck = "overwatch"
        self.table.game.uno_pending[2] = self.now + 3
        hand = HandView(self.cog, self.table, 1)
        self.addCleanup(hand.stop)
        original, old_view = self.table.message, self.table.view
        deadline = self.table.game.turn_deadline
        await self.chat(10)
        sent = self.thread.send.await_args.kwargs
        self.assertEqual(sent["file"].filename, "uno-top.png")
        self.assertIsInstance(sent["view"], GameView)
        self.assertIn("Overwatch", sent["embed"].footer.text)
        self.assertNotIn("attachments", sent)
        self.assertEqual(self.table.game.turn_deadline, deadline)
        self.assertEqual(self.table.game.uno_pending[2], self.now + 3)
        self.assertEqual(self.table.game.revision, hand.revision)
        self.assertTrue(old_view.is_finished())
        original.delete.assert_awaited_once()
        self.users[1].send.assert_awaited_once()
        await self.cog.act(self.interaction(1), self.table, "play", card_ids=["play"], revision=hand.revision)
        self.table.message.edit.assert_awaited_once()
        self.assertEqual(self.table.game.current_player, 2)

    async def test_unrelated_bot_private_and_old_messages_do_not_count(self):
        other_thread = Mock(spec=nextcord.Thread)
        other_thread.id = 52
        messages = [self.chat_message(channel=other_thread),
                    self.chat_message(channel=Mock(spec=nextcord.TextChannel)),
                    self.chat_message(author=SimpleNamespace(bot=True))]
        private = self.chat_message()
        private.guild = None
        messages.append(private)
        old = self.chat_message()
        old.id = self.table.message.id - 1
        messages.append(old)
        for message in messages:
            await self.cog.on_message(message)
        self.assertEqual(self.table.message_count, 0)
        for status in ("finishing", "finished", "cancelled"):
            self.table.status = status
            await self.chat(10)
        self.assertEqual(self.table.message_count, 0)
        self.thread.send.assert_awaited_once()

    async def test_message_counts_are_separate_for_each_table(self):
        other_thread = Mock(spec=nextcord.Thread)
        other_thread.id = 52
        other_thread.send = AsyncMock(side_effect=lambda **kwargs: self.board())
        other = Table("other", 10, 50, 3, {3: "Jogador 3"}, thread=other_thread)
        self.cog.tables[other.id] = other
        await self.cog.refresh_lobby(other)
        await self.chat(9)
        for _ in range(9):
            await self.cog.on_message(self.chat_message(channel=other_thread))
        await self.chat(1)
        self.assertEqual(self.thread.send.await_count, 2)
        other_thread.send.assert_awaited_once()
        await self.cog.on_message(self.chat_message(channel=other_thread))
        self.assertEqual(other_thread.send.await_count, 2)

    async def test_concurrent_messages_repost_once_and_queued_old_events_are_ignored(self):
        await self.start()
        await asyncio.gather(*(self.cog.on_message(self.chat_message()) for _ in range(10)))
        self.assertEqual(self.thread.send.await_count, 2)
        queued = self.chat_message()
        await self.chat(10)
        self.assertEqual(self.thread.send.await_count, 3)
        await self.cog.on_message(queued)
        self.assertEqual(self.table.message_count, 0)

    async def test_failed_repost_preserves_controls_and_retries_on_next_message(self):
        await self.start()
        original, old_view = self.table.message, self.table.view
        self.thread.send.side_effect = forbidden()
        with self.assertLogs("cogs.uno", level="ERROR"):
            await self.chat(10)
        self.assertIs(self.table.message, original)
        self.assertIs(self.table.view, old_view)
        self.assertFalse(old_view.is_finished())
        original.delete.assert_not_awaited()
        self.assertEqual(self.table.status, "playing")
        self.thread.send.side_effect = lambda **kwargs: self.board()
        await self.chat(1)
        self.assertIsNot(self.table.message, original)
        original.delete.assert_awaited_once()

    async def test_failed_old_board_deletion_removes_its_controls(self):
        original = self.table.message
        original.delete.side_effect = forbidden()
        original.edit.reset_mock()
        await self.chat(10)
        original.edit.assert_awaited_once_with(view=None)
        self.assertIsNot(self.table.message, original)
        self.assertFalse(self.table.view.is_finished())

    async def test_turn_dm_mentions_only_current_player_and_links_to_thread(self):
        await self.start()
        notice = self.users[1].send.await_args
        self.assertIn("<@1>", notice.args[0])
        self.assertIn("https://discord.com/channels/10/51", notice.args[0])
        self.assertNotIn("<@2>", notice.args[0])
        self.assertEqual(notice.kwargs["allowed_mentions"].to_dict(),
                         {"parse": [], "users": [1]})
        self.users[2].send.assert_not_awaited()
        self.set_cards()
        await self.cog.act(self.interaction(1), self.table, "play", card_ids=["play"])
        await self.table.notification_task
        self.users[2].send.assert_awaited_once()

    async def test_repeated_publications_uno_call_and_playable_draw_do_not_repeat_dm(self):
        await self.start()
        self.set_cards()
        self.table.game.hands[1] = [Card("single", "red", "3")]
        self.table.game.uno_pending[1] = self.now + 3
        await self.cog.publish(self.table)
        await self.cog.act(self.interaction(1), self.table, "call_uno")
        self.table.game.draw_pile = [Card("drawn", "red", "7")]
        await self.cog.act(self.interaction(1), self.table, "draw")
        await self.table.notification_task
        self.assertEqual(self.table.game.current_player, 1)
        self.users[1].send.assert_awaited_once()

    async def test_new_turn_for_same_player_and_timeout_send_new_notices(self):
        await self.start()
        self.set_cards(value="skip")
        self.now += 1
        await self.cog.act(self.interaction(1), self.table, "play", card_ids=["play"])
        await self.table.notification_task
        self.assertEqual(self.table.game.current_player, 1)
        self.assertEqual(self.users[1].send.await_count, 2)
        self.now = self.table.game.turn_deadline
        await Uno.tick.coro(self.cog)
        await self.table.notification_task
        self.assertEqual(self.table.game.current_player, 2)
        self.users[2].send.assert_awaited_once()

    async def test_closed_dms_do_not_cancel_match_or_repeat_attempts_in_same_turn(self):
        self.users[1].send.side_effect = forbidden()
        with self.assertLogs("cogs.uno", level="WARNING"):
            await self.start()
        await self.cog.publish(self.table)
        await self.table.notification_task
        self.assertEqual(self.table.status, "playing")
        self.assertIn(self.table.id, self.cog.tables)
        self.users[1].send.assert_awaited_once()

    async def test_uncached_user_is_fetched_and_fetch_failure_is_nonfatal(self):
        self.bot.get_user.side_effect = None
        self.bot.get_user.return_value = None
        self.bot.fetch_user.return_value = self.users[1]
        await self.start()
        self.bot.fetch_user.assert_awaited_once_with(1)
        self.users[1].send.assert_awaited_once()
        self.bot.fetch_user.side_effect = forbidden()
        self.now = self.table.game.turn_deadline
        with self.assertLogs("cogs.uno", level="WARNING"):
            await Uno.tick.coro(self.cog)
            await self.table.notification_task
        self.assertEqual(self.table.status, "playing")

    async def test_slow_dm_does_not_block_play_and_is_cancelled_when_game_ends(self):
        sending = asyncio.Event()

        async def slow_send(*args, **kwargs):
            sending.set()
            await asyncio.Event().wait()

        self.users[1].send.side_effect = slow_send
        await self.cog.lobby_action(self.table, self.users[1], "start")
        await asyncio.wait_for(sending.wait(), timeout=1)
        task = self.table.notification_task
        self.set_cards()
        self.table.game.hands[1] = [Card("play", "red", "3")]
        await asyncio.wait_for(self.cog.act(self.interaction(1), self.table, "play", card_ids=["play"]), timeout=1)
        await asyncio.sleep(0)
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.table.notification_task)
        self.assertEqual(self.table.status, "finished")
        self.users[2].send.assert_not_awaited()

    async def test_slow_user_lookup_does_not_notify_a_player_whose_turn_ended(self):
        fetching, resume = asyncio.Event(), asyncio.Event()

        async def fetch_user(player_id):
            fetching.set()
            await resume.wait()
            return self.users[player_id]

        self.bot.get_user.side_effect = None
        self.bot.get_user.return_value = None
        self.bot.fetch_user.side_effect = fetch_user
        await self.cog.lobby_action(self.table, self.users[1], "start")
        await asyncio.wait_for(fetching.wait(), timeout=1)
        # A turn can change while Discord is still resolving the previous user.
        self.now = self.table.game.turn_deadline
        self.table.game.timeout(now=self.now)
        resume.set()
        await self.table.notification_task
        self.users[1].send.assert_not_awaited()
        await self.cog.publish(self.table)
        await self.table.notification_task
        self.users[2].send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
