"""Atomic poker buy-ins, payouts, game exclusivity and crash recovery."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import unittest

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from db import Database, EconomyError


class PokerStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "poker.db").as_posix()
        self.db = Database(self.url)
        for pid in range(1, 4):
            self.db.add_balance(pid, 1000)

    def tearDown(self):
        self.db.engine.dispose()
        self.directory.cleanup()

    def test_insufficient_player_rolls_back_every_buyin(self):
        self.db.set_balance(2, 10)
        with self.assertRaises(EconomyError):
            self.db.start_poker_game("a", [1, 2], 100)
        self.assertEqual(self.db.balance(1), 1000)
        self.assertEqual(self.db.balance(2), 10)
        self.assertEqual(self.db.recover_poker_games(), 0)

    def test_solo_bots_are_funded_without_discord_accounts(self):
        receipt = self.db.start_poker_game("solo", [1], 100, bots=4)
        self.assertEqual(receipt["seats"], [1, -1, -2, -3, -4])
        self.assertEqual(receipt["total"], 500)
        self.assertEqual(self.db.balance(1), 900)
        self.db.finish_poker_game("solo", {1: 500, -1: 0, -2: 0, -3: 0, -4: 0})
        self.assertEqual(self.db.balance(1), 1400)
        self.assertEqual(self.db.leaderboard()[1], 3)

    def test_bad_seats_or_totals_cannot_mint_chips(self):
        self.db.start_poker_game("a", [1, 2], 100)
        for stacks in ({1: 201, 2: 0}, {1: 200}, {1: -1, 2: 201}, {1: True, 2: 199},
                       {"1": 100, 2: 100}, {1: 100, 3: 100}, {1: 100.0, 2: 100}):
            with self.subTest(stacks=stacks), self.assertRaises(EconomyError):
                self.db.finish_poker_game("a", stacks)
        self.assertEqual([self.db.balance(pid) for pid in (1, 2)], [900, 900])
        with self.assertRaises(EconomyError):
            self.db.settle_bet("poker:a:1", 999)

    def test_concurrent_finishes_and_late_cancel_pay_once(self):
        self.db.start_poker_game("a", [1, 2], 100)
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.db.finish_poker_game("a", {1: 150, 2: 50}), range(4)))
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual(self.db.cancel_poker_game("a"), receipts[0])
        self.assertEqual([self.db.balance(pid) for pid in (1, 2)], [1050, 950])

    def test_restart_refunds_and_late_finish_does_not_pay_again(self):
        self.db.start_poker_game("a", [1, 2], 100)
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.db.recover_bets(), 2)
        self.assertEqual(self.db.recover_poker_games(), 0)
        receipt = self.db.finish_poker_game("a", {1: 200, 2: 0})
        self.assertEqual(receipt["status"], "refunded")
        self.assertEqual([self.db.balance(pid) for pid in (1, 2)], [1000, 1000])
        self.assertEqual(self.db.recover_bets(), 0)
        self.db.start_poker_game("new", [1, 2], 100)

    def test_poker_cog_recovery_leaves_other_games_untouched(self):
        self.db.start_poker_game("a", [1], 100, bots=4)
        bet = self.db.reserve_bet(2, "blackjack", 50)
        self.assertEqual(self.db.recover_poker_games(), 1)
        self.assertEqual(self.db.balance(1), 1000)
        self.assertEqual(self.db.balance(2), 950)
        self.db.settle_bet(bet, 0)

    def test_games_reserve_humans_exclusively_both_directions(self):
        self.db.start_poker_game("a", [1, 2], 100)
        for start in (lambda: self.db.reserve_bet(1, "slots", 10),
                      lambda: self.db.start_uno_game("u", [1, 3], 0),
                      lambda: self.db.start_poker_game("b", [1, 3], 100)):
            with self.assertRaises(EconomyError):
                start()
        self.db.cancel_poker_game("a")
        self.db.start_uno_game("u", [1, 2], 0)
        with self.assertRaises(EconomyError):
            self.db.start_poker_game("b", [1, 3], 100)
        self.db.cancel_uno_game("u")
        self.db.reserve_bet(1, "slots", 10)
        with self.assertRaises(EconomyError):
            self.db.start_poker_game("b", [1, 3], 100)

    def test_invalid_lobby_settings_never_debit(self):
        for ids, stake, bots in (([1], 100, 0), ([1, 2], 100, 4), ([1, 1], 100, 0),
                                 ([1, 2], 19, 0), ([1, 2], True, 0), ([], 100, 0)):
            with self.assertRaises(EconomyError):
                self.db.start_poker_game("a", ids, stake, bots=bots)
        self.assertEqual(self.db.balance(1), 1000)
