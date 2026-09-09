"""Offline tests; never read the live database or connect to Discord."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import product
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from PIL import Image
from nextcord.ext import commands
from db import Database, EconomyError, MAX_BALANCE, database
from amounts import parse_amount
from game_rules import Blackjack, Mines, RNG, SLOT_SYMBOLS, hand_value, slot_multiplier, mines_multiplier
from games import BlackjackView, MinesView, MineCountSelect, Games
from leaderboard import render_leaderboard, Leaderboard
from main import create_bot


def deck_for(player, dealer, draws=()):
    return list(reversed([player[0], dealer[0], player[1], dealer[1], *draws]))


def tearDownModule():
    database.engine.dispose()


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "test.db").as_posix()
        self.db = Database(self.url)
        self.db.add_balance(1, 1000)

    def tearDown(self):
        self.db.engine.dispose()
        self.directory.cleanup()

    def test_invalid_bets_and_insufficient_balance_leave_wallet_unchanged(self):
        for amount in (0, -1, 1.5, True, 10 ** 50, 1001):
            with self.assertRaises(EconomyError):
                self.db.reserve_bet(1, "mines", amount)
        self.assertEqual(self.db.balance(1), 1000)

    def test_reservation_settlement_and_duplicate_settlement(self):
        bet = self.db.reserve_bet(1, "blackjack", 100)
        self.assertEqual(self.db.balance(1), 900)
        with self.assertRaises(EconomyError):
            self.db.reserve_bet(1, "mines", 100)
        self.assertEqual(self.db.settle_bet(bet, 250), 1150)
        self.assertEqual(self.db.settle_bet(bet, 250), 1150)
        self.assertEqual(self.db.settle_bet(bet), 1150)

    def test_set_and_reset_balance_validate_and_persist(self):
        for amount in (-1, True, 1.5, "100", MAX_BALANCE + 1):
            with self.assertRaises(EconomyError):
                self.db.set_balance(1, amount)
            self.assertEqual(self.db.balance(1), 1000)
        self.assertEqual(self.db.set_balance(1, MAX_BALANCE), MAX_BALANCE)
        self.assertEqual(self.db.set_balance(2, 1234), 1234)
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.db.balance(1), MAX_BALANCE)
        self.assertEqual(self.db.balance(2), 1234)
        self.assertEqual(self.db.reset_balance(1), 0)
        self.assertEqual(self.db.reset_balance(3), 0)
        self.assertEqual(self.db.set_balance(2, 0), 0)

    def test_reset_changes_available_balance_and_keeps_active_bet_settlement(self):
        bet = self.db.reserve_bet(1, "mines", 100)
        self.db.reset_balance(1)
        self.assertEqual(self.db.balance(1), 0)
        self.assertEqual(self.db.settle_bet(bet, 200), 200)
        self.assertEqual(self.db.settle_bet(bet, 200), 200)

    def test_uncapped_bets_and_balance_aliases(self):
        self.db.add_balance(1, 5_000_001)
        bet = self.db.reserve_bet(1, "mines", "half")
        self.assertEqual(self.db.bet_stake(bet), 2_500_500)
        self.assertEqual(self.db.balance(1), 2_500_501)
        self.db.settle_bet(bet)
        bet = self.db.reserve_bet(1, "mines", "all")
        self.assertEqual(self.db.bet_stake(bet), 5_001_001)
        self.assertEqual(self.db.balance(1), 0)
        self.db.settle_bet(bet)
        bet = self.db.reserve_bet(1, "blackjack", 5_000_000)
        self.assertEqual(self.db.bet_stake(bet), 5_000_000)
        self.db.settle_bet(bet)
        for alias in ("half", "all"):
            with self.assertRaises(EconomyError):
                self.db.reserve_bet(2, "mines", alias)
        self.db.add_balance(2, 1)
        with self.assertRaises(EconomyError):
            self.db.reserve_bet(2, "mines", "half")
        self.assertEqual(self.db.bet_stake(self.db.reserve_bet(2, "mines", "all")), 1)

    def test_huge_winnings_persist_rank_and_refund_exactly(self):
        amounts = {"1": 2 ** 63 - 1, "2": 2 ** 63, "3": 10 ** 21,
                   "4": 10 ** 20 + 1, "5": 10 ** 20, "6": 10 ** 80 + 123,
                   "7": 10 ** 20}
        for user_id, amount in amounts.items():
            if user_id != "1":
                self.db.add_balance(user_id, 1000)
            bet = self.db.reserve_bet(user_id, "slots", "all")
            self.db.settle_bet(bet, amount)
            self.db.settle_bet(bet, amount)
        self.db.engine.dispose()
        self.db = Database(self.url)
        for user_id, amount in amounts.items():
            self.assertEqual(self.db.balance(user_id), amount)
        rows, _ = self.db.leaderboard()
        self.assertEqual([user_id for user_id, _ in rows], ["6", "3", "4", "5", "7", "2", "1"])
        for rank, (user_id, amount) in enumerate(rows, start=1):
            self.assertEqual(self.db.profile(user_id)["rank"], rank)
        bet = self.db.reserve_bet(6, "mines", "half")
        self.assertEqual(self.db.bet_stake(bet), amounts["6"] // 2)
        self.assertEqual(self.db.recover_bets(), 1)
        self.assertEqual(self.db.balance(6), amounts["6"])
        self.assertEqual(self.db.recover_bets(), 0)

    def test_large_mines_win_can_be_bet_all_without_overflow(self):
        self.db.add_balance(2, MAX_BALANCE)
        bet = self.db.reserve_bet(2, "mines", "all")
        game = Mines(self.db.bet_stake(bet), 8, mines=set(range(8)))
        for cell in range(8, 16):
            game.reveal(cell)
        self.assertGreater(game.payout, 2 ** 63)
        self.db.settle_bet(bet, game.payout)
        self.assertEqual(self.db.balance(2), game.payout)
        bet = self.db.reserve_bet(2, "slots", "all")
        self.assertEqual(self.db.bet_stake(bet), game.payout)
        self.db.settle_bet(bet, game.payout * 10)
        self.assertEqual(self.db.balance(2), game.payout * 10)

    def test_restart_refunds_only_pending_games_once(self):
        self.db.reserve_bet(1, "mines", 500)
        self.db.add_balance(2, 1000)
        finished = self.db.reserve_bet(2, "slots", 100)
        self.db.settle_bet(finished, 0)
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.db.recover_bets(), 1)
        self.assertEqual(self.db.recover_bets(), 0)
        self.assertEqual(self.db.balance(1), 1000)
        self.assertEqual(self.db.balance(2), 900)

    def test_simultaneous_reservations_and_payouts(self):
        def reserve(_):
            try:
                return self.db.reserve_bet(1, "blackjack", 600)
            except EconomyError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            bets = list(pool.map(reserve, range(4)))
        self.assertEqual(sum(bet is not None for bet in bets), 1)
        self.assertEqual(self.db.balance(1), 400)
        bet = next(bet for bet in bets if bet)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.db.settle_bet(bet, 1200), range(4)))
        self.assertEqual(self.db.balance(1), 1600)

    def test_simultaneous_all_bets_reserve_the_wallet_once(self):
        def reserve(_):
            try:
                return self.db.reserve_bet(1, "mines", "all")
            except EconomyError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            bets = list(pool.map(reserve, range(4)))
        successful = [bet for bet in bets if bet]
        self.assertEqual(len(successful), 1)
        self.assertEqual(self.db.bet_stake(successful[0]), 1000)
        self.assertEqual(self.db.balance(1), 0)

    def test_transfer_cannot_spend_reserved_funds_and_rolls_back_overflow(self):
        bet = self.db.reserve_bet(1, "mines", 600)
        with self.assertRaises(EconomyError):
            self.db.transfer(1, 2, 500)
        self.db.add_balance(2, MAX_BALANCE)
        with self.assertRaises(EconomyError):
            self.db.transfer(1, 2, 100)
        self.assertEqual(self.db.balance(1), 400)
        self.db.transfer(1, 1, 100)
        self.assertEqual(self.db.balance(1), 400)
        self.db.settle_bet(bet)
        self.assertEqual(self.db.balance(1), 1000)

    def test_daily_claim_persists_and_reports_only_actual_reward(self):
        self.assertEqual(self.db.daily(1, 5000, now=100000), 6000)
        self.db.engine.dispose()
        self.db = Database(self.url)
        with self.assertRaisesRegex(EconomyError, "<t:183600:R>"):
            self.db.daily(1, 5000, now=100001)
        with self.assertRaisesRegex(EconomyError, "<t:183600:R>"):
            self.db.daily(1, 5000, now=183599)
        self.assertEqual(self.db.daily(1, 5000, now=183600), 11000)

    def test_daily_resets_at_gmt_minus_three_midnight_including_calendar_boundaries(self):
        for day in ("2026-09-08", "2027-01-01", "2028-03-01"):
            with self.subTest(day=day):
                midnight = int(datetime.fromisoformat(f"{day}T03:00:00+00:00").timestamp())
                before = self.db.balance(1)
                self.db.daily(1, 5000, now=midnight - 1)
                self.db.daily(1, 5000, now=midnight)
                self.assertEqual(self.db.balance(1), before + 10000)
                # UTC midnight is still 21:00 GMT-3 on the same claim day.
                for now in (midnight + 1, midnight + 21 * 3600, midnight + 86400 - 1):
                    with self.assertRaisesRegex(EconomyError, f"<t:{midnight + 86400}:R>"):
                        self.db.daily(1, 5000, now=now)
                self.assertEqual(self.db.balance(1), before + 10000)

    def test_simultaneous_daily_claims_pay_once_per_gmt_minus_three_day(self):
        def claim(_):
            try:
                return self.db.daily(1, 5000, now=100000)
            except EconomyError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            balances = list(pool.map(claim, range(4)))
        self.assertEqual([balance for balance in balances if balance is not None], [6000])
        self.assertEqual(self.db.balance(1), 6000)

    def test_ranking_is_sorted_stable_and_paginated(self):
        self.db.add_balance(2, 2000)
        self.db.add_balance(3, 2000)
        self.assertEqual(self.db.leaderboard(1, 2), ([("2", 2000), ("3", 2000)], 3))
        self.assertEqual(self.db.leaderboard(2, 2), ([("1", 1000)], 3))

    def test_legacy_users_table_is_preserved(self):
        path = Path(self.directory.name) / "legacy.db"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, discord_id VARCHAR UNIQUE, balance INTEGER)")
            connection.execute("INSERT INTO users (discord_id, balance) VALUES ('42', 4321)")
        connection.close()
        legacy = Database("sqlite:///" + path.as_posix())
        try:
            self.assertEqual(legacy.balance(42), 4321)
            legacy.reserve_bet(42, "mines", 100)
            self.assertEqual(legacy.balance(42), 4221)
        finally:
            legacy.engine.dispose()


class RuleTests(unittest.TestCase):
    def test_amount_suffixes_are_exact_and_case_insensitive(self):
        for value, expected in {"100": 100, "10k": 10_000, "1m": 1_000_000,
                                "10K": 10_000, "1M": 1_000_000, "1.5k": 1500,
                                "0.25m": 250_000, "0.001k": 1, "0.000001m": 1,
                                "0.029k": 29, " 10k ": 10_000, "half": "half",
                                "ALL": "all", " Half ": "half", "9" * 100: int("9" * 100)}.items():
            with self.subTest(value=value):
                self.assertEqual(parse_amount(value), expected)
        for value in ("0", "-1k", "1.2", "0k", "0.0001k", "0.0000001m", "10kk",
                      "1e3", "NaN", "inf", "1,000", "1 k", "k", "", "9" * 5000, "allk", "halff"):
            with self.subTest(value=value), self.assertRaises(commands.BadArgument):
                parse_amount(value)

    def test_all_slot_outcomes_and_expected_return(self):
        returns = [slot_multiplier(reels) for reels in product(SLOT_SYMBOLS, repeat=3)]
        self.assertEqual(len(returns), 216)
        self.assertEqual(sum(returns), 208)
        self.assertEqual(slot_multiplier(("💎",) * 3), 10)
        self.assertEqual(slot_multiplier(("🍒", "🍒", "💎")), 2)
        self.assertEqual(slot_multiplier(("🍒", "🍋", "💎")), 0)

    def test_aces(self):
        self.assertEqual(hand_value([("A", "♠"), ("A", "♥"), ("9", "♣")]), 21)
        self.assertEqual(hand_value([("A", "♠"), ("6", "♥")]), 17)
        self.assertEqual(hand_value([("A", "♠"), ("6", "♥"), ("K", "♣")]), 17)

    def test_naturals_and_odd_stake_rounding(self):
        player = [("A", "♠"), ("K", "♠")]
        normal = [("10", "♥"), ("9", "♥")]
        for p, d, payout in [(player, normal, 252), (normal, player, 0), (player, player, 101)]:
            game = Blackjack(101, deck_for(p, d))
            self.assertEqual(game.payout, payout)

    def test_blackjack_win_loss_push_bust_and_soft_17(self):
        cases = [
            ([("10", "♠"), ("9", "♠")], [("10", "♥"), ("8", "♥")], [], "stand", 200),
            ([("10", "♠"), ("8", "♠")], [("10", "♥"), ("9", "♥")], [], "stand", 0),
            ([("10", "♠"), ("8", "♠")], [("10", "♥"), ("8", "♥")], [], "stand", 100),
            ([("10", "♠"), ("6", "♠")], [("10", "♥"), ("8", "♥")], [("K", "♣")], "hit", 0),
            ([("10", "♠"), ("8", "♠")], [("A", "♥"), ("6", "♥")], [], "stand", 200),
            ([("10", "♠"), ("8", "♠")], [("10", "♥"), ("6", "♥")], [("K", "♣")], "stand", 200),
            ([("10", "♠"), ("6", "♠")], [("10", "♥"), ("8", "♥")], [("5", "♣")], "hit", 200),
        ]
        for player, dealer, draws, action, expected in cases:
            with self.subTest(action=action, player=player, dealer=dealer):
                game = Blackjack(100, deck_for(player, dealer, draws))
                getattr(game, action)()
                self.assertEqual(game.payout, expected)
                game.hit()
                game.stand()
                self.assertEqual(game.payout, expected)

    def test_mines_risk_cashout_loss_duplicate_click_and_completion(self):
        game = Mines(100, 3, mines={0, 1, 2})
        game.cashout()
        self.assertIsNone(game.payout)
        game.reveal(3)
        self.assertEqual(game.cashout_value(), 119)
        game.reveal(3)
        self.assertEqual(len(game.revealed), 1)
        game.cashout()
        self.assertEqual(game.payout, 119)
        game.reveal(0)
        self.assertEqual(game.payout, 119)
        lost = Mines(100, 3, mines={0, 1, 2})
        lost.reveal(0)
        self.assertEqual(lost.payout, 0)
        complete = Mines(100, 15, mines=set(range(15)))
        complete.reveal(15)
        self.assertEqual(complete.payout, 1552)

    def test_every_mines_configuration_has_increasing_returns(self):
        for count in range(1, 16):
            game = Mines(100, count, mines=set(range(count)))
            previous = game.multiplier(0)
            for safe in range(1, 17 - count):
                self.assertGreater(game.multiplier(safe), previous)
                previous = game.multiplier(safe)
        for count in (0, 16, -1, True):
            with self.assertRaises(ValueError):
                Mines(100, count)

    def test_more_bombs_increases_multiplier_for_same_number_of_safe_tiles(self):
        for revealed in range(1, 16):
            multipliers = [mines_multiplier(count, revealed) for count in range(1, 17 - revealed)]
            for lower, higher in zip(multipliers, multipliers[1:]):
                self.assertGreater(higher, lower)


class DiscordTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.db.add_balance(1, 1000)
        self.views = []

    async def asyncTearDown(self):
        for view in self.views:
            view.stop()
        self.db.engine.dispose()

    def interaction(self, user_id=1):
        return SimpleNamespace(user=SimpleNamespace(id=user_id),
                               response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()),
                               message=SimpleNamespace(edit=AsyncMock()))

    def view(self, game, view_type=MinesView):
        bet = self.db.reserve_bet(1, "test", game.stake)
        view = view_type(1, bet, game, storage=self.db)
        self.views.append(view)
        return view

    async def test_extensions_and_aliases_load_without_network(self):
        bot = create_bot()
        try:
            for name in ("ping", "balance", "daily", "pay", "addbalance", "rich", "slots", "blackjack", "mines"):
                self.assertIsNotNone(bot.get_command(name))
            for alias, name in (("top", "rich"), ("bj", "blackjack"), ("slot", "slots"), ("minas", "mines"), ("pix", "pay")):
                self.assertIs(bot.get_command(alias), bot.get_command(name))
        finally:
            await bot.close()

    async def test_rich_and_slots_command_invocation_with_per_user_cooldowns(self):
        bot = create_bot()
        bot._connection.user = SimpleNamespace(id=999)
        bot.get_cog("Leaderboard").storage = self.db
        bot.get_cog("Games").storage = self.db
        self.db.add_balance(2, 1000)

        async def context(content, user_id=1, seconds=0):
            message = SimpleNamespace(
                content=content, author=SimpleNamespace(id=user_id), guild=None,
                channel=SimpleNamespace(id=123), attachments=[], edited_at=None,
                created_at=datetime.fromtimestamp(1_800_000_000 + seconds, timezone.utc),
                _state=bot._connection,
            )
            ctx = await bot.get_context(message)
            ctx.send = AsyncMock()
            return ctx

        try:
            for command, alias, cooldown in (("r.rich", "r.top", 5), ("r.slots 100", "r.slot 100", 3)):
                with self.subTest(command=command):
                    first = await context(command)
                    await first.command.invoke(first)
                    first.send.assert_awaited_once()
                    if command == "r.rich":
                        self.assertEqual(first.send.call_args.kwargs["file"].filename, "rich-list.png")
                    repeat = await context(alias, seconds=1)
                    with self.assertRaises(commands.CommandOnCooldown):
                        await repeat.command.invoke(repeat)
                    repeat.send.assert_not_awaited()
                    other_user = await context(command, user_id=2, seconds=1)
                    await other_user.command.invoke(other_user)
                    other_user.send.assert_awaited_once()
                    expired = await context(command, seconds=cooldown + 1)
                    await expired.command.invoke(expired)
                    expired.send.assert_awaited_once()
        finally:
            await bot.close()

    async def test_bet_shortcuts_through_all_game_commands_and_aliases(self):
        bot = create_bot()
        bot._connection.user = SimpleNamespace(id=999)
        bot.get_cog("Games").storage = self.db
        self.db.add_balance(1, 10_000_000)
        seconds = 0

        async def context(content, user_id=1):
            nonlocal seconds
            seconds += 5
            message = SimpleNamespace(content=content, author=SimpleNamespace(id=user_id), guild=None,
                                      channel=SimpleNamespace(id=123), attachments=[], edited_at=None,
                                      created_at=datetime.fromtimestamp(1_800_000_000 + seconds, timezone.utc),
                                      _state=bot._connection)
            ctx = await bot.get_context(message)
            ctx.send = AsyncMock()
            return ctx

        try:
            for content, expected in (("r.slots 10k", 10_000), ("r.slot 1m", 1_000_000),
                                      ("r.blackjack 1.5k", 1500), ("r.bj 1M", 1_000_000),
                                      ("r.mines 10K 5", 10_000), ("r.minas 5m", 5_000_000),
                                      ("r.slots half", "half"), ("r.slot ALL", "all"),
                                      ("r.blackjack HALF", "half"), ("r.bj all", "all"),
                                      ("r.mines half 5", "half"), ("r.minas all", "all")):
                with self.subTest(content=content):
                    if isinstance(expected, str):
                        self.db.add_balance(1, 2_000_001)
                        balance = self.db.balance(1)
                        expected = balance if expected == "all" else balance // 2
                    ctx = await context(content)
                    with patch.object(RNG, "choice", side_effect=["🍒", "🍋", "💎"]):
                        await ctx.command.invoke(ctx)
                    ctx.send.assert_awaited_once()
                    view = ctx.send.call_args.kwargs.get("view")
                    if view:
                        self.views.append(view)
                        self.assertEqual(view.game.stake, expected)
                        await view.on_timeout()
                    else:
                        self.assertIn(f"{expected:,}", ctx.send.call_args.kwargs["embed"].fields[0].value)
            previous = self.db.balance(1)
            for content in (f"r.slots {previous + 1}", f"r.blackjack {previous + 1}", f"r.mines {previous + 1}"):
                ctx = await context(content)
                with self.assertRaises(commands.CommandInvokeError) as caught:
                    await ctx.command.invoke(ctx)
                self.assertIsInstance(caught.exception.original, EconomyError)
                self.assertEqual(self.db.balance(1), previous)
            for content in ("r.slots 0.0001k", "r.blackjack -1m", "r.mines 10kk"):
                ctx = await context(content)
                with self.assertRaises(commands.BadArgument):
                    await ctx.command.invoke(ctx)
                self.assertEqual(self.db.balance(1), previous)
            self.db.add_balance(2, 1000)
            ctx = await context("r.mines 1m", user_id=2)
            with self.assertRaises(commands.CommandInvokeError) as caught:
                await ctx.command.invoke(ctx)
            self.assertIsInstance(caught.exception.original, EconomyError)
            self.assertEqual(self.db.balance(2), 1000)
        finally:
            await bot.close()

    async def test_owner_only_and_simultaneous_cashouts(self):
        game = Mines(100, 3, mines={0, 1, 2})
        view = self.view(game)
        intruder = self.interaction(2)
        await view.act(intruder, lambda: game.reveal(3))
        self.assertFalse(game.revealed)
        intruder.response.send_message.assert_awaited_once()
        await view.act(self.interaction(), lambda: game.reveal(3))
        await asyncio.gather(view.act(self.interaction(), game.cashout), view.act(self.interaction(), game.cashout))
        self.assertEqual(self.db.balance(1), 1019)
        self.assertTrue(all(item.disabled for item in view.children))
        await view.on_timeout()
        self.assertEqual(self.db.balance(1), 1019)

    async def test_mines_timeout_refunds_unplayed_and_cashouts_played(self):
        view = self.view(Mines(100, 3, mines={0, 1, 2}))
        await view.on_timeout()
        self.assertEqual(self.db.balance(1), 1000)
        view = self.view(Mines(100, 3, mines={0, 1, 2}))
        view.game.reveal(3)
        await view.on_timeout()
        self.assertEqual(self.db.balance(1), 1019)

    async def test_blackjack_timeout_stands_and_hides_hole_card_until_finished(self):
        game = Blackjack(100, deck_for([("10", "♠"), ("9", "♠")], [("10", "♥"), ("8", "♥")]))
        view = self.view(game, BlackjackView)
        self.assertNotIn("8♥", view.embed().fields[1].value)
        await view.on_timeout()
        self.assertIn("8♥", view.embed().fields[1].value)
        self.assertEqual(self.db.balance(1), 1100)

    async def test_mines_component_limits_and_reveal(self):
        view = self.view(Mines(100, 3, mines={0, 1, 2}))
        view.embed()
        self.assertEqual(len(view.children), 17)
        self.assertTrue(view.cashout.disabled)
        self.assertLessEqual(len(view.to_components()), 5)
        await view.act(self.interaction(), lambda: view.game.reveal(3))
        self.assertFalse(view.cashout.disabled)
        await view.act(self.interaction(), lambda: view.game.reveal(0))
        self.assertTrue(view.done)
        self.assertEqual(self.db.balance(1), 900)

    async def test_send_failure_refunds_unsettled_bet(self):
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), send=AsyncMock(side_effect=RuntimeError("send failed")))
        with self.assertRaises(RuntimeError):
            await Games(None, self.db).start_game(ctx, 100, "mines", Mines, MinesView)
        self.assertEqual(self.db.balance(1), 1000)

    async def test_slots_command_pays_actual_reels_and_failed_send_cannot_pay_again(self):
        cog = Games(None, self.db)
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), send=AsyncMock())
        with patch.object(RNG, "choice", return_value="💎"):
            await Games.slots.callback(cog, ctx, 100)
        self.assertEqual(self.db.balance(1), 1900)
        self.assertIn("1,000", ctx.send.call_args.kwargs["embed"].fields[1].value)
        ctx.send.side_effect = RuntimeError("send failed")
        with patch.object(RNG, "choice", side_effect=["🍒", "🍋", "💎"]):
            with self.assertRaises(RuntimeError):
                await Games.slots.callback(cog, ctx, 100)
        self.assertEqual(self.db.balance(1), 1800)

    async def test_game_commands_wire_buttons_and_naturals_settle_immediately(self):
        cog = Games(None, self.db)
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), send=AsyncMock())
        await Games.mines.callback(cog, ctx, 100, 3)
        view = ctx.send.call_args.kwargs["view"]
        self.views.append(view)
        self.assertEqual(self.db.balance(1), 900)
        self.assertIsNotNone(view.message)
        with self.assertRaises(EconomyError):
            await Games.blackjack.callback(cog, ctx, 100)
        await view.on_timeout()
        game = Blackjack(100, deck_for([("A", "♠"), ("K", "♠")], [("10", "♥"), ("8", "♥")]))
        await cog.start_game(ctx, 100, "blackjack", lambda stake: game, BlackjackView)
        view = ctx.send.call_args.kwargs["view"]
        self.views.append(view)
        self.assertTrue(view.done)
        self.assertEqual(self.db.balance(1), 1150)
        self.assertTrue(all(item.disabled for item in view.children))

    async def test_mines_prompts_owner_then_starts_with_chosen_bombs_once(self):
        cog = Games(None, self.db)
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), send=AsyncMock())
        await Games.mines.callback(cog, ctx, 100)
        view = ctx.send.call_args.kwargs["view"]
        self.views.append(view)
        self.assertTrue(view.choosing)
        self.assertEqual(self.db.balance(1), 900)
        self.assertEqual(len(view.children), 1)
        menu = view.children[0]
        self.assertIsInstance(menu, MineCountSelect)
        self.assertEqual([option.value for option in menu.options], [str(i) for i in range(1, 16)])
        self.assertIn("15.52", menu.options[-1].label)
        self.assertIn("1,552", menu.options[-1].description)
        # Emulate the selected value supplied by Discord.
        menu._selected_values = ["10"]
        await menu.callback(self.interaction(2))
        self.assertTrue(view.choosing)
        await asyncio.gather(menu.callback(self.interaction()), menu.callback(self.interaction()))
        self.assertFalse(view.choosing)
        self.assertEqual(len(view.game.mines), 10)
        self.assertEqual(len(view.children), 17)
        self.assertEqual(self.db.balance(1), 900)
        self.assertIn("258", view.embed().fields[3].value)
        original_board = view.game
        view.choose_bombs(15)
        self.assertIs(view.game, original_board)
        safe = next(cell for cell in range(16) if cell not in view.game.mines)
        await view.act(self.interaction(), lambda: view.game.reveal(safe))
        await view.act(self.interaction(), view.game.cashout)
        self.assertEqual(self.db.balance(1), 1158)

    async def test_mines_selection_timeout_refunds_and_cannot_start_late(self):
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), send=AsyncMock())
        await Games.mines.callback(Games(None, self.db), ctx, 100)
        view = ctx.send.call_args.kwargs["view"]
        self.views.append(view)
        await view.on_timeout()
        self.assertEqual(self.db.balance(1), 1000)
        self.assertTrue(view.done)
        self.assertTrue(all(item.disabled for item in view.children))
        await view.act(self.interaction(), lambda: view.choose_bombs(15))
        self.assertTrue(view.choosing)
        self.assertEqual(self.db.balance(1), 1000)

    async def test_mines_rejects_invalid_explicit_bomb_counts_before_debit(self):
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), send=AsyncMock())
        for count in (0, -1, 16, 100):
            with self.assertRaises(EconomyError):
                await Games.mines.callback(Games(None, self.db), ctx, 100, count)
        self.assertEqual(self.db.balance(1), 1000)
        ctx.send.assert_not_awaited()

    async def test_rich_command_attaches_png_and_validates_pages(self):
        ctx = SimpleNamespace(author=SimpleNamespace(id=1), guild=None, send=AsyncMock())
        bot = SimpleNamespace(get_user=lambda _: SimpleNamespace(display_name="Ralsei"))
        cog = Leaderboard(bot, self.db)
        await Leaderboard.rich.callback(cog, ctx, 1)
        attachment = ctx.send.call_args.kwargs["file"]
        self.assertEqual(attachment.filename, "rich-list.png")
        for page in (0, 2, -1, 10**20):
            with self.assertRaises(EconomyError):
                await Leaderboard.rich.callback(cog, ctx, page)


class ImageTests(unittest.TestCase):
    def test_png_for_empty_long_unicode_and_full_page(self):
        for entries in ([], [(1, "💚 Ralsei 日本語 " * 30, MAX_BALANCE, True)],
                        [(i, f"Jogador {i}", i * 1000, False) for i in range(1, 11)]):
            with render_leaderboard(entries, 1, 1, len(entries)) as output:
                with Image.open(output) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.width, 1000)
                    self.assertLessEqual(image.height, 1100)
                    image.verify()


if __name__ == "__main__":
    unittest.main()
