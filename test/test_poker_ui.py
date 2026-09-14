"""Offline Discord interactions, privacy and failure recovery for poker."""
import asyncio
from io import BytesIO
import os
from pathlib import Path
import random
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from PIL import Image
import nextcord
import cogs.poker as poker_module

from cogs.poker import Poker, PokerView, RaiseModal, Table, TURN_SECONDS
from cogs.poker_rules import Holdem, Player, PokerError, full_deck
import cogs.poker_render as renderer
from db import Database, EconomyError


def picture():
    output = BytesIO()
    Image.new("RGB", (256, 256), "#bf5279").save(output, "PNG")
    return output.getvalue()


class PokerUITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        for pid in (1, 2, 3):
            self.db.add_balance(pid, 1000)
        self.now = 0
        avatar = SimpleNamespace(read=AsyncMock(return_value=picture()))
        avatar.with_size = Mock(return_value=avatar)
        avatar.with_static_format = Mock(return_value=avatar)
        self.avatar = avatar
        self.cog = Poker(SimpleNamespace(user=SimpleNamespace(display_avatar=avatar)), self.db, lambda: self.now)
        self.message = SimpleNamespace(id=101, edit=AsyncMock())
        self.ctx = SimpleNamespace(author=self.user(1), channel=SimpleNamespace(id=10),
                                   guild=SimpleNamespace(id=20), send=AsyncMock(return_value=self.message))

    async def asyncTearDown(self):
        self.cog.cog_unload()
        self.db.engine.dispose()

    @staticmethod
    def user(pid):
        return SimpleNamespace(id=pid, display_name=f"Pessoa {pid}", bot=False)

    def interaction(self, pid):
        return SimpleNamespace(user=self.user(pid),
            response=SimpleNamespace(defer=AsyncMock(), is_done=Mock(return_value=True),
                                     send_message=AsyncMock(), send_modal=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    async def table(self, people=(1, 2), *, start=True):
        await self.cog.poker.callback(self.cog, self.ctx, 100)
        table = next(iter(self.cog.tables.values()))
        for pid in people[1:]:
            await self.cog.lobby_action(table, self.user(pid), "join")
        if start:
            await self.cog.lobby_action(table, self.user(1), "start")
        return table

    async def test_command_uses_actual_discord_avatar_and_never_debits_lobby(self):
        table = await self.table(start=False)
        self.avatar.read.assert_awaited_once()
        self.avatar.with_static_format.assert_called_once_with("png")
        self.assertEqual(table.dealer_avatar, picture())
        self.assertEqual([self.db.balance(pid) for pid in (1, 2)], [1000, 1000])
        self.assertEqual(len(table.view.children), 4)

    async def test_solo_adds_four_bots_but_multiplayer_has_only_humans(self):
        solo = await self.table(people=(1,))
        self.assertEqual([p.name for p in solo.game.players if p.bot], ["Kris", "Susie", "Lancer", "Noelle"])
        self.assertEqual(len(solo.game.players), 5)
        self.assertEqual(self.db.balance(1), 900)
        await self.cog.cancel(solo)
        multiplayer = await self.table()
        self.assertEqual(len(multiplayer.game.players), 2)
        self.assertFalse(any(p.bot for p in multiplayer.game.players))

    async def test_only_host_can_start_and_cannot_cancel_after_seeing_cards(self):
        table = await self.table(start=False)
        with self.assertRaises(PokerError):
            await self.cog.lobby_action(table, self.user(2), "start")
        await self.cog.lobby_action(table, self.user(1), "start")
        with self.assertRaises(PokerError):
            await self.cog.lobby_action(table, self.user(1), "cancel")
        self.assertEqual(self.db.balance(1), 900)

    async def test_host_leaving_transfers_ownership_and_membership_is_exclusive(self):
        table = await self.table(start=False)
        with self.assertRaises(EconomyError):
            await self.cog.poker.callback(self.cog, self.ctx, 100)
        await self.cog.lobby_action(table, self.user(1), "leave")
        self.assertEqual(table.host_id, 2)
        self.assertNotIn(1, self.cog.memberships)
        await self.cog.lobby_action(table, self.user(2), "leave")
        self.assertEqual(table.status, "cancelled")
        self.assertFalse(self.cog.tables)

    async def test_insufficient_balance_at_start_keeps_everyones_wallet_intact(self):
        table = await self.table(start=False)
        self.db.set_balance(2, 10)
        with self.assertRaises(EconomyError):
            await self.cog.lobby_action(table, self.user(1), "start")
        self.assertEqual(table.status, "lobby")
        self.assertIsNone(table.game)
        self.assertEqual(self.db.balance(1), 1000)

    async def test_private_hands_reject_spectators_and_preserve_turn_deadline(self):
        table = await self.table()
        deadline = table.deadline
        outsider = self.interaction(3)
        with self.assertRaises(PokerError):
            await self.cog.show_hand(table, outsider)
        outsider.followup.send.assert_not_awaited()
        interaction = self.interaction(1)
        await self.cog.show_hand(table, interaction)
        self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])
        self.assertEqual(interaction.followup.send.call_args.kwargs["file"].filename, "poker-hand.png")
        self.assertEqual(table.deadline, deadline)

    async def test_concurrent_clicks_apply_exactly_one_action(self):
        table = await self.table()
        pid, revision = table.game.actor.id, table.game.revision
        results = await asyncio.gather(self.cog.play(table, pid, revision, "call"),
                                       self.cog.play(table, pid, revision, "call"), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, PokerError) for result in results), 1)
        self.assertEqual(table.game.revision, revision + 1)

    async def test_old_raise_modal_cannot_act_on_a_new_turn(self):
        table = await self.table()
        pid = table.game.actor.id
        modal = RaiseModal(self.cog, table, table.game.revision, pid)
        modal.amount.refresh_state({"value": "20"}, state=Mock(), guild=None)
        await self.cog.play(table, pid, table.game.revision, "call")
        interaction = self.interaction(pid)
        await modal.callback(interaction)
        self.assertIn("mesa mudou", interaction.followup.send.call_args.args[0])
        self.assertEqual(table.game.revision, 1)
        modal.stop()

    async def test_timeout_checks_when_free_and_folds_when_facing_a_bet(self):
        table = await self.table()
        await self.cog.play(table, table.game.actor.id, table.game.revision, "call")
        self.now = table.deadline
        await self.cog.tick_table(table)
        self.assertEqual(table.game.street, "flop")
        self.assertIn("Mesa", table.game.log[-1])
        await self.cog.play(table, table.game.actor.id, table.game.revision, "raise", 10)
        self.now = table.deadline
        await self.cog.tick_table(table)
        self.assertTrue(table.game.done)
        self.assertIn("Desistiu", table.game.log[-1])
        self.assertEqual(sum(self.db.balance(pid) for pid in (1, 2)), 2000)

    async def test_deadline_starts_after_table_upload_finishes(self):
        table = await self.table()

        async def slow_upload(**kwargs):
            self.now = 20

        self.message.edit.side_effect = slow_upload
        await self.cog.play(table, table.game.actor.id, table.game.revision, "call")
        self.assertEqual(table.deadline, 20 + TURN_SECONDS)

    async def test_live_bot_turn_receives_no_opponents_private_cards(self):
        table = await self.table(people=(1,))
        if not table.game.actor.bot:
            await self.cog.play(table, 1, table.game.revision, "call")
        own_cards = tuple(table.game.actor.cards)
        self.now = table.deadline
        with patch.object(poker_module, "bot_decision", return_value=("call", None)) as decide:
            await self.cog.tick_table(table)
        self.assertEqual(decide.call_args.args, (own_cards, ()))
        self.assertEqual(decide.call_args.kwargs["opponents"], 4)
        self.assertNotIn("game", decide.call_args.kwargs)

    async def test_failed_start_upload_and_deleted_messages_refund_once(self):
        table = await self.table(start=False)
        self.message.edit.side_effect = RuntimeError("upload failed")
        with self.assertRaises(RuntimeError):
            await self.cog.lobby_action(table, self.user(1), "start")
        self.assertEqual(table.status, "cancelled")
        self.assertEqual(self.db.balance(1), 1000)
        self.message.edit.side_effect = None
        table = await self.table()
        await self.cog.on_raw_message_delete(SimpleNamespace(message_id=101))
        await self.cog.on_raw_message_delete(SimpleNamespace(message_id=101))
        self.assertEqual([self.db.balance(pid) for pid in (1, 2)], [1000, 1000])

    async def test_finished_payout_survives_failed_receipt_delivery(self):
        table = await self.table()
        self.message.edit.side_effect = RuntimeError("upload failed")
        with self.assertRaises(RuntimeError):
            await self.cog.play(table, table.game.actor.id, table.game.revision, "fold")
        self.assertEqual(table.status, "finished")
        self.assertEqual(table.receipt["status"], "settled")
        self.assertEqual(sum(self.db.balance(pid) for pid in (1, 2)), 2000)
        self.assertFalse(self.cog.memberships)
        self.assertEqual(self.db.recover_poker_games(), 0)

    async def test_expiration_and_unload_release_tables_and_reservations(self):
        table = await self.table(start=False)
        self.now = table.deadline
        await self.cog.tick_table(table)
        self.assertFalse(self.cog.tables)
        table = await self.table()
        self.cog.cog_unload()
        self.assertFalse(self.cog.memberships)
        self.assertEqual(self.db.balance(1), 1000)
        self.assertEqual(self.db.recover_poker_games(), 0)


class PokerRenderTests(unittest.TestCase):
    def test_every_face_uses_an_existing_card_asset(self):
        for card in full_deck():
            self.assertTrue((renderer.ASSETS / "cards" / card.filename).is_file())
            self.assertEqual(renderer.card_image(card).size, (68, 99))

    def test_public_image_hides_holes_then_reveals_only_showdown_survivors(self):
        game = Holdem([Player(1, "Caio", 100), Player(2, "Amigo", 100), Player(3, "Kris", 100)],
                      rng=random.Random(9))
        with patch.object(renderer, "card_image", wraps=renderer.card_image) as load:
            output = renderer.render_table(game.players, game=game, dealer_avatar=picture())
            self.assertTrue(all(call.args[0] is None for call in load.call_args_list))
        with Image.open(output) as image:
            self.assertEqual(image.size, (1200, 820))
            self.assertEqual(image.getpixel((600, 186)), (191, 82, 121))
        game.act(1, "fold")
        while not game.done:
            game.act(game.actor.id, "call" if game.to_call(game.actor) else "check")
        with patch.object(renderer, "card_image", wraps=renderer.card_image) as load:
            renderer.render_table(game.players, game=game)
        shown = [call.args[0] for call in load.call_args_list]
        self.assertTrue(all(card not in shown for card in game.players[0].cards))
        self.assertEqual(set(shown), set(game.board + game.players[1].cards + game.players[2].cards))

    def test_private_image_contains_only_the_requested_players_cards(self):
        game = Holdem([Player(1, "Caio", 100), Player(2, "Amigo", 100)])
        with patch.object(renderer, "card_image", wraps=renderer.card_image) as load:
            output = renderer.render_hand(game.players[0])
        self.assertEqual([call.args[0] for call in load.call_args_list], game.players[0].cards)
        with Image.open(output) as image:
            self.assertEqual(image.size, (680, 400))
