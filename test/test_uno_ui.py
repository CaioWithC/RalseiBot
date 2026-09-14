"""Offline Discord flows backed by the real Six engine and isolated storage."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
import cogs.uno as uno_module

from cogs.uno import ChannelPanel, ColorView, GameView, HandView, SwapView, Uno
from cogs.uno_rules import Card, RuleError, Rules
from db import Database, EconomyError


class UnoUITests(unittest.IsolatedAsyncioTestCase):
    async def test_select_payloads_have_unique_custom_ids_and_route_callbacks(self):
        table = await self.table(players=(1,))
        lobby = table.view
        panel = self.retain(ChannelPanel(self.cog, self.channel, self.member(3, moderator=True)))
        await self.cog.lobby_action(table, self.member(2), "join")
        await self.cog.lobby_action(table, self.member(), "start")
        hand = self.retain(HandView(self.cog, table, 1))
        swap = self.retain(SwapView(hand))
        identifiers = set()
        for view in (lobby, panel, hand, swap):
            with self.subTest(view=type(view).__name__):
                components = [component for row in view.to_components() for component in row["components"]]
                for component in components:
                    custom_id = component.get("custom_id")
                    self.assertIsInstance(custom_id, str)
                    self.assertTrue(1 <= len(custom_id) <= 100)
                    self.assertNotIn(custom_id, identifiers)
                    identifiers.add(custom_id)
                for select in (item for item in view.children if isinstance(item, nextcord.ui.Select)):
                    payload = select.to_component_dict()
                    self.assertEqual(payload["custom_id"], select.custom_id)
                    values = [select.options[0].value]
                    interaction = self.interaction()
                    select.refresh_state({"custom_id": payload["custom_id"], "values": values},
                                         state=Mock(), guild=None)
                    with patch.object(select, "handler", new_callable=AsyncMock) as handler:
                        await select.callback(interaction)
                        handler.assert_awaited_once_with(interaction, values)

    async def test_only_host_can_choose_one_of_three_decks_before_start(self):
        table = await self.table()
        view = table.view
        select = next(item for item in view.children if isinstance(item, nextcord.ui.Select)
                      and item.placeholder == "Baralho da mesa")
        self.assertEqual([option.value for option in select.options], ["normal", "meme", "overwatch"])
        self.assertEqual([len(row["components"]) for row in view.to_components()], [1, 1, 1, 1, 4])
        with self.assertRaises(RuleError):
            await view.set_deck(self.interaction(2), ["meme"])
        with self.assertRaises(RuleError):
            await view.set_deck(self.interaction(), ["../../custom"])
        for deck in ("meme", "overwatch", "normal"):
            await table.view.set_deck(self.interaction(), [deck])
            self.assertEqual(table.deck, deck)
            self.assertEqual(table.ready, {1, 2})
        await self.cog.lobby_action(table, self.member(), "start")
        with self.assertRaises(RuleError):
            await view.set_deck(self.interaction(), ["meme"])
        self.assertEqual(table.deck, "normal")

    async def test_selected_deck_reaches_public_and_private_images(self):
        from cogs.uno_render import render_card, render_hand
        table = await self.table()
        await table.view.set_deck(self.interaction(), ["overwatch"])
        with patch.object(uno_module, "render_card", wraps=render_card) as top, patch.object(uno_module, "render_hand", wraps=render_hand) as hand:
            await self.cog.lobby_action(table, self.member(), "start")
            await self.cog.show_hand(self.interaction(), table)
        self.assertEqual(top.call_args.kwargs["deck"], "overwatch")
        self.assertEqual(hand.call_args.kwargs["deck"], "overwatch")
        self.assertIn("Overwatch", self.cog.game_embed(table).footer.text)

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Database("sqlite:///" + (Path(self.directory.name) / "uno-ui.db").as_posix())
        self.now = 1000.0
        self.guild = SimpleNamespace(id=10, me=object())
        self.message = SimpleNamespace(id=102, edit=AsyncMock())
        self.thread = Mock(spec=nextcord.Thread)
        self.thread.id, self.thread.guild, self.thread.mention = 51, self.guild, "<#51>"
        self.thread.send = AsyncMock(return_value=self.message)
        self.invite = SimpleNamespace(id=101, edit=AsyncMock(), create_thread=AsyncMock(return_value=self.thread))
        self.channel = Mock(spec=nextcord.TextChannel)
        self.channel.id, self.channel.guild = 50, self.guild
        self.channel.send = AsyncMock(return_value=self.invite)
        self.channel.permissions_for.return_value = nextcord.Permissions.all()
        self.cog = Uno(Mock(), self.db, clock=lambda: self.now)
        self.views = []
        for player in (1, 2, 3):
            self.db.add_balance(player, 1000)

    async def asyncTearDown(self):
        for view in self.views:
            view.stop()
        for table in list(self.cog.tables.values()):
            await self.cog.cancel(table, "Fim do teste")
        self.cog.cog_unload()
        self.db.engine.dispose()
        self.directory.cleanup()

    def member(self, user_id=1, *, moderator=False, bot=False):
        return SimpleNamespace(id=user_id, display_name=f"Jogador {user_id}", bot=bot,
                               guild_permissions=nextcord.Permissions(manage_messages=moderator))

    def interaction(self, user_id=1, *, moderator=False):
        response = SimpleNamespace(done=False)

        async def acknowledge(*args, **kwargs):
            if response.done:
                raise AssertionError("A mesma interação foi respondida duas vezes")
            response.done = True

        response.is_done = lambda: response.done
        response.defer = AsyncMock(side_effect=acknowledge)
        response.send_message = AsyncMock(side_effect=acknowledge)
        interaction = SimpleNamespace(user=self.member(user_id, moderator=moderator), guild=self.guild,
                                      response=response, followup=SimpleNamespace(send=AsyncMock()),
                                      edit_original_message=AsyncMock(), message=self.message)
        return interaction

    def retain(self, view):
        self.views.append(view)
        return view

    async def table(self, *, players=(1, 2), stake=0, start=False, rules=None):
        table = await self.cog.create_table(self.channel, self.member(players[0]))
        table.stake = stake
        if rules is not None:
            table.rules = rules
        for player in players[1:]:
            await self.cog.lobby_action(table, self.member(player), "join")
        if start:
            await self.cog.lobby_action(table, self.member(players[0]), "start")
        return table

    def set_hand(self, table, cards, *, player=1):
        # Fixed examples make UI action checks independent of the shuffled deal.
        table.game.hands[player] = cards
        table.game.discard_pile = [Card("top", "red", "5")]
        table.game.current_color = "red"
        table.game.current_player = player

    async def test_create_uses_invite_public_thread_and_lists_staff_controls(self):
        table = await self.table(players=(1,))
        self.invite.create_thread.assert_awaited_once_with(name="Uno - Jogador 1", auto_archive_duration=1440)
        self.assertEqual(table.thread, self.thread)
        self.assertEqual(self.cog.memberships, {1: table.id})
        self.assertEqual(table.ready, {1})
        public = self.channel.send.await_args.kwargs
        self.assertNotIn("ephemeral", public)
        self.assertIn("Entrar", [button.label for button in public["view"].children])
        for moderator in (False, True):
            panel = self.retain(ChannelPanel(self.cog, self.channel, self.member(3, moderator=moderator)))
            selects = [item for item in panel.children if isinstance(item, nextcord.ui.Select)]
            self.assertEqual(len(selects), int(moderator))
        with self.assertRaises(RuleError):
            await self.cog.create_table(self.channel, self.member())
        self.channel.send.assert_awaited_once()

    async def test_missing_thread_permissions_fail_before_sending_anything(self):
        self.channel.permissions_for.return_value = nextcord.Permissions(view_channel=True, send_messages=True)
        with self.assertRaises(RuleError):
            await self.cog.create_table(self.channel, self.member())
        self.channel.send.assert_not_awaited()
        self.assertFalse(self.cog.tables)
        self.assertFalse(self.cog.memberships)

    async def test_failed_thread_creation_cleans_registry_and_invite(self):
        self.invite.create_thread.side_effect = nextcord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions")
        with self.assertRaises(nextcord.Forbidden):
            await self.cog.create_table(self.channel, self.member())
        self.assertFalse(self.cog.tables)
        self.assertFalse(self.cog.memberships)
        view = self.invite.edit.await_args.kwargs["view"]
        self.assertTrue(all(button.disabled for button in view.children))

    async def test_player_capacity_and_host_transfer_keep_lobby_consistent(self):
        table = await self.table(players=tuple(range(1, 21)))
        with self.assertRaises(RuleError):
            await self.cog.lobby_action(table, self.member(21), "join")
        with self.assertRaises(RuleError):
            await self.cog.lobby_action(table, self.member(99, bot=True), "join")
        self.assertEqual(len(table.members), 20)
        await self.cog.lobby_action(table, self.member(), "leave")
        self.assertEqual(table.host_id, 2)
        self.assertNotIn(1, self.cog.memberships)
        await self.cog.lobby_action(table, self.member(21), "join")
        self.assertEqual(len(table.members), 20)

    async def test_twenty_real_snowflakes_fit_discord_embed_limits(self):
        players = tuple(700_000_000_000_000_000 + number for number in range(20))
        table = await self.table(players=players)
        lobby = self.message.edit.await_args.kwargs["embed"]
        await self.cog.lobby_action(table, self.member(players[0]), "start")
        table.game.uno_called = set(players)
        table.game.uno_pending = {player: self.now + 3 for player in players}
        await self.cog.publish(table)
        playing = self.message.edit.await_args.kwargs["embed"]
        for embed in (lobby, playing):
            with self.subTest(title=embed.title):
                self.assertLessEqual(len(embed), 6000)
                self.assertLessEqual(len(embed.title or ""), 256)
                self.assertLessEqual(len(embed.description or ""), 4096)
                self.assertLessEqual(len(embed.fields), 25)
                for field in embed.fields:
                    self.assertLessEqual(len(field.name), 256)
                    self.assertLessEqual(len(field.value), 1024)
        listed = "\n".join(field.value for field in playing.fields if field.name.startswith("Jogadores"))
        for player in players:
            self.assertIn(f"<@{player}>", listed)

    async def test_staff_panel_cancels_active_table_and_rechecks_permissions(self):
        table = await self.table(start=True, stake=100)
        panel = self.retain(ChannelPanel(self.cog, self.channel, self.member(3, moderator=True)))
        with self.assertRaises(RuleError):
            await panel.close_table(self.interaction(3), [table.id])
        self.assertEqual(table.status, "playing")
        await panel.close_table(self.interaction(3, moderator=True), [table.id])
        self.assertEqual(table.status, "cancelled")
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1000, 1000])

    async def test_host_authorization_and_changed_stake_require_new_acceptance(self):
        table = await self.table()
        view = table.view
        for action in ("start", "cancel"):
            with self.assertRaises(RuleError):
                await self.cog.lobby_action(table, self.member(2), action)
        with self.assertRaises(RuleError):
            await view.set_stake(self.interaction(2), ["100"])
        self.assertEqual(table.stake, 0)
        await view.set_stake(self.interaction(), ["100"])
        self.assertEqual(table.stake, 100)
        self.assertEqual(table.ready, {1})
        with self.assertRaises(RuleError):
            await self.cog.lobby_action(table, self.member(), "start")
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1000, 1000])
        await self.cog.lobby_action(table, self.member(2), "join")
        await self.cog.lobby_action(table, self.member(), "start")
        self.assertEqual(table.status, "playing")
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [900, 900])

    async def test_balance_spent_after_acceptance_cannot_partially_fund_game(self):
        table = await self.table(stake=100)
        self.db.set_balance(2, 50)
        with self.assertRaises(EconomyError):
            await self.cog.lobby_action(table, self.member(), "start")
        self.assertEqual(table.status, "lobby")
        self.assertIsNone(table.game)
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1000, 50])
        self.db.add_balance(2, 50)
        await self.cog.lobby_action(table, self.member(), "start")
        self.assertEqual(table.status, "playing")

    async def test_private_hand_and_public_table_never_expose_other_hands(self):
        table = await self.table(start=True)
        self.set_hand(table, [Card("private-number", "yellow", "9"), Card("private-action", "blue", "skip")])
        await self.cog.publish(table)
        public = self.message.edit.await_args.kwargs
        self.assertEqual(public["file"].filename, "uno-top.png")
        self.assertIsInstance(public["view"], GameView)
        self.assertFalse(any(isinstance(item, nextcord.ui.Select) for item in public["view"].children))
        public_text = str(public["embed"].to_dict())
        self.assertNotIn("Bloqueio", public_text)
        self.assertNotIn("Amarelo", public_text)
        public_edits = self.message.edit.await_count
        interaction = self.interaction()
        await table.view.hand(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        private = interaction.followup.send.await_args.kwargs
        self.assertTrue(private["ephemeral"])
        self.assertEqual(private["file"].filename, "uno-hand.png")
        hand = self.retain(private["view"])
        self.assertEqual([card.uid for card in hand.cards], ["private-number", "private-action"])
        self.assertEqual(self.message.edit.await_count, public_edits)
        self.assertFalse(await hand.interaction_check(self.interaction(2)))
        with self.assertRaises(RuleError):
            await self.cog.show_hand(self.interaction(3), table)

    async def test_stale_selection_confirmation_and_draw_cannot_mutate_game(self):
        table = await self.table(start=True)
        self.set_hand(table, [Card("playable", "red", "3"), Card("keep", "blue", "4")])
        hand = self.retain(HandView(self.cog, table, 1, selected=("playable",)))
        table.game.revision += 1
        before = list(table.game.hands[1])
        for action in (
            lambda: hand.select_cards(self.interaction(), ["playable"]),
            lambda: hand.confirm(self.interaction()),
            lambda: hand.draw(self.interaction()),
        ):
            with self.assertRaises(RuleError):
                await action()
            self.assertEqual(table.game.hands[1], before)
        refreshed = self.interaction()
        await hand.back(refreshed)
        new_hand = self.retain(refreshed.edit_original_message.await_args.kwargs["view"])
        self.assertEqual(new_hand.revision, table.game.revision)

    async def test_select_then_confirm_commits_once_and_predeclares_uno(self):
        table = await self.table(start=True)
        playable, keep = Card("playable", "red", "3"), Card("keep", "blue", "4")
        self.set_hand(table, [playable, keep])
        hand = self.retain(HandView(self.cog, table, 1))
        selection = self.interaction()
        await hand.select_cards(selection, [playable.uid])
        selected = self.retain(selection.edit_original_message.await_args.kwargs["view"])
        self.assertEqual(table.game.hands[1], [playable, keep])
        declared = self.interaction()
        await selected.predeclare(declared)
        confirmation = self.retain(declared.edit_original_message.await_args.kwargs["view"])
        await confirmation.confirm(self.interaction())
        self.assertEqual(table.game.hands[1], [keep])
        self.assertEqual(table.game.top, playable)
        self.assertIn(1, table.game.uno_called)
        with self.assertRaises(RuleError):
            await confirmation.confirm(self.interaction())

    async def test_wild_requires_color_and_color_view_is_owner_restricted(self):
        table = await self.table(start=True)
        wild, keep = Card("wild", None, "wild4"), Card("keep", "blue", "4")
        self.set_hand(table, [wild, keep])
        hand = self.retain(HandView(self.cog, table, 1, selected=(wild.uid,)))
        interaction = self.interaction()
        await hand.confirm(interaction)
        colors = self.retain(interaction.edit_original_message.await_args.kwargs["view"])
        self.assertIsInstance(colors, ColorView)
        self.assertEqual(table.game.hands[1], [wild, keep])
        self.assertFalse(await colors.interaction_check(self.interaction(2)))
        blue = next(button for button in colors.children if button.label.endswith("Azul"))
        await blue.callback(self.interaction())
        self.assertEqual(table.game.current_color, "blue")
        self.assertEqual(table.game.top, wild)
        self.assertEqual(table.game.pending_draw, 4)
        self.assertIsNotNone(table.game.challenge)

    async def test_seven_requires_target_before_swapping_hands(self):
        table = await self.table(players=(1, 2, 3), rules=Rules(seven_zero=True), start=True)
        seven, keep = Card("seven", "red", "7"), Card("keep", "blue", "4")
        other = [Card("other-a", "yellow", "2"), Card("other-b", "green", "3")]
        self.set_hand(table, [seven, keep])
        table.game.hands[2] = other
        hand = self.retain(HandView(self.cog, table, 1, selected=(seven.uid,)))
        interaction = self.interaction()
        await hand.confirm(interaction)
        swap = self.retain(interaction.edit_original_message.await_args.kwargs["view"])
        self.assertIsInstance(swap, SwapView)
        self.assertEqual([option.value for option in swap.children[0].options], ["2", "3"])
        self.assertEqual(table.game.hands[1], [seven, keep])
        await swap.choose(self.interaction(), ["2"])
        self.assertEqual(table.game.hands[1], other)
        self.assertEqual(table.game.hands[2], [keep])
        self.assertIn(2, table.game.uno_pending)

    async def test_hands_larger_than_select_limit_are_paginated(self):
        table = await self.table(start=True, rules=Rules(multiple_cards=True))
        self.set_hand(table, [Card(f"card-{n}", "red", str(n % 10)) for n in range(31)])
        interaction = self.interaction()
        await self.cog.show_hand(interaction, table)
        first = self.retain(interaction.followup.send.await_args.kwargs["view"])
        choices = next(item for item in first.children if isinstance(item, nextcord.ui.Select))
        self.assertEqual(len(choices.options), 25)
        self.assertEqual(choices.max_values, 25)
        next_page = self.interaction()
        await first.next_page(next_page)
        second = self.retain(next_page.edit_original_message.await_args.kwargs["view"])
        self.assertEqual([card.uid for card in second.cards], [f"card-{n}" for n in range(25, 31)])
        self.assertEqual(second.page, 1)
        select = self.interaction()
        await second.select_cards(select, ["card-30"])
        confirm = self.retain(select.edit_original_message.await_args.kwargs["view"])
        await confirm.confirm(self.interaction())
        self.assertEqual(table.game.top.uid, "card-30")
        self.assertEqual(len(table.game.hands[1]), 30)

    async def test_tick_times_out_turn_and_updates_uno_buttons_after_three_seconds(self):
        table = await self.table(start=True)
        self.set_hand(table, [Card("only", "red", "3")])
        table.game.uno_pending[1] = self.now + 3
        await self.cog.publish(table)
        shout = next(item for item in table.view.children if item.label == "Gritar Uno!")
        catch = next(item for item in table.view.children if item.label == "Pegar! (+2)")
        self.assertFalse(shout.disabled)
        self.assertTrue(catch.disabled)
        self.now += 3.1
        await self.cog.tick()
        shout = next(item for item in table.view.children if item.label == "Gritar Uno!")
        catch = next(item for item in table.view.children if item.label == "Pegar! (+2)")
        self.assertTrue(shout.disabled)
        self.assertFalse(catch.disabled)
        self.assertEqual(set(self.message.edit.await_args.kwargs), {"view"})
        self.now = table.game.turn_deadline
        before = len(table.game.hands[1])
        await self.cog.tick()
        self.assertEqual(len(table.game.hands[1]), before + 1)
        self.assertEqual(table.game.current_player, 2)
        self.assertGreater(table.game.turn_deadline, self.now)

    async def test_action_after_deadline_applies_timeout_instead_of_selected_card(self):
        table = await self.table(start=True)
        playable = Card("late", "red", "3")
        self.set_hand(table, [playable, Card("keep", "green", "4")])
        view = self.retain(HandView(self.cog, table, 1, selected=(playable.uid,)))
        self.now = table.game.turn_deadline
        with self.assertRaises(RuleError):
            await view.confirm(self.interaction())
        self.assertIn(playable, table.game.hands[1])
        self.assertEqual(len(table.game.hands[1]), 3)
        self.assertEqual(table.game.current_player, 2)

    async def test_cancel_and_thread_deletion_refund_once_and_release_players(self):
        table = await self.table(start=True, stake=100)
        await self.cog.on_thread_delete(self.thread)
        await self.cog.cancel(table, "Cancelamento repetido")
        self.assertEqual(table.status, "cancelled")
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1000, 1000])
        self.assertFalse(self.cog.tables)
        self.assertFalse(self.cog.memberships)
        self.assertIsNone(self.message.edit.await_args.kwargs["view"])
        self.assertTrue(all(button.disabled for button in table.invite_view.children))

    async def test_expired_lobby_releases_members_without_taking_money(self):
        table = await self.table(stake=100)
        self.now = table.created_at + 900
        await self.cog.tick()
        self.assertEqual(table.status, "cancelled")
        self.assertFalse(self.cog.memberships)
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1000, 1000])

    async def test_failed_first_game_publish_refunds_committed_escrow(self):
        table = await self.table(stake=100)
        error = nextcord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions")
        self.message.edit.side_effect = [error, None]
        with self.assertRaises(nextcord.Forbidden):
            await self.cog.lobby_action(table, self.member(), "start")
        self.assertEqual(table.status, "cancelled")
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1000, 1000])
        self.assertFalse(self.cog.memberships)

    async def test_final_card_settles_rewards_and_removes_private_controls(self):
        table = await self.table(start=True, stake=100)
        final = Card("final", "red", "3")
        self.set_hand(table, [final])
        hand = self.retain(HandView(self.cog, table, 1, selected=(final.uid,)))
        interaction = self.interaction()
        await hand.confirm(interaction)
        self.assertEqual(table.status, "finished")
        self.assertEqual(table.receipt["winners"], [1])
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1135, 905])
        self.assertFalse(self.cog.memberships)
        self.assertIsNone(self.message.edit.await_args.kwargs["view"])
        self.assertIsNone(interaction.edit_original_message.await_args.kwargs["view"])
        with self.assertRaises(RuleError):
            await hand.confirm(self.interaction())
        self.assertEqual([self.db.balance(uid) for uid in (1, 2)], [1135, 905])


if __name__ == "__main__":
    unittest.main()
