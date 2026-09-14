"""Offline transactional tests for Six tables; never open the live database."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from db import Database, EconomyError


class UnoStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "uno.db").as_posix()
        self.db = Database(self.url)
        for player_id in range(1, 5):
            self.db.add_balance(player_id, 1000)

    def tearDown(self):
        self.db.engine.dispose()
        self.directory.cleanup()

    def balances(self, players=(1, 2, 3)):
        return [self.db.balance(player_id) for player_id in players]

    def test_start_debits_everyone_or_no_one(self):
        self.db.set_balance(3, 9)
        with self.assertRaises(EconomyError):
            self.db.start_uno_game("table", [1, 2, 3], 10)
        self.assertEqual(self.balances(), [1000, 1000, 9])
        self.db.add_balance(3, 1)
        receipt = self.db.start_uno_game("table", [1, 2, 3], 10)
        self.assertEqual(receipt["status"], "active")
        self.assertEqual(receipt["pot"], 30)
        self.assertEqual(self.balances(), [990, 990, 0])
        with self.assertRaises(EconomyError):
            self.db.start_uno_game("table", [1, 2, 3], 10)
        self.assertEqual(self.balances(), [990, 990, 0])

    def test_invalid_start_never_debits_or_reserves_players(self):
        cases = [("table", [1, 2], value) for value in (-1, True, 1.5, "all")]
        cases += [(game_id, [1, 2], 10) for game_id in (None, "", " ")]
        cases += [("table", players, 10) for players in (
            [], [1], [1, 1], [True, 2], [0, 2], ["1", 2], list(range(1, 22))) ]
        for game_id, players, stake in cases:
            with self.subTest(game_id=game_id, players=players, stake=stake):
                with self.assertRaises(EconomyError):
                    self.db.start_uno_game(game_id, players, stake)
                self.assertEqual(self.balances(), [1000, 1000, 1000])
        self.assertEqual(self.db.recover_uno_games(), 0)
        self.db.start_uno_game("table", [1, 2], 10)

    def test_casual_game_rewards_once_and_survives_restart(self):
        self.db.start_uno_game("casual", [1, 2, 3], 0)
        receipt = self.db.finish_uno_game("casual", [2])
        self.assertEqual(receipt["status"], "settled")
        self.assertEqual(receipt["players"], [1, 2, 3])
        self.assertEqual(receipt["winners"], [2])
        self.assertEqual(receipt["rewards"], {1: 5, 2: 35, 3: 5})
        self.assertEqual(receipt["payouts"], {2: 0})
        self.assertEqual(self.balances(), [1005, 1035, 1005])
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.db.finish_uno_game("casual", [2]), receipt)
        self.assertEqual(self.db.cancel_uno_game("casual"), receipt)
        self.assertEqual(self.db.recover_uno_games(), 0)
        self.assertEqual(self.balances(), [1005, 1035, 1005])
        self.db.start_uno_game("next", [1, 2], 0)

    def test_entire_pot_is_split_in_winner_order(self):
        self.db.start_uno_game("split", [1, 2, 3], 5)
        receipt = self.db.finish_uno_game("split", [2, 1])
        self.assertEqual(receipt["pot"], 15)
        self.assertEqual(receipt["payouts"], {2: 8, 1: 7})
        self.assertEqual(receipt["rewards"], {1: 5, 2: 35, 3: 5})
        self.assertEqual(self.balances(), [1007, 1038, 1000])
        self.assertEqual(sum(self.balances()), 3045)

    def test_forfeiting_players_get_no_participation_reward(self):
        self.db.start_uno_game("forfeit", [1, 2, 3], 10)
        receipt = self.db.finish_uno_game("forfeit", [1], participants=[1, 3])
        self.assertEqual(receipt["participants"], [1, 3])
        self.assertEqual(receipt["rewards"], {1: 35, 3: 5})
        self.assertEqual(receipt["payouts"], {1: 30})
        self.assertEqual(self.balances(), [1055, 990, 995])
        self.assertEqual(self.db.finish_uno_game("forfeit", [1]), receipt)

    def test_invalid_results_leave_money_and_reservation_intact(self):
        self.db.start_uno_game("table", [1, 2, 3], 10)
        cases = [([], None), ([1, 1], None), ([99], None), ([1, 2, 3], None),
                 ([True], None), ([1], []), ([1], [2, 3]), ([1], [1, 99]),
                 ([1], [1, 1]), ([1], [1, True])]
        for winners, participants in cases:
            with self.subTest(winners=winners, participants=participants):
                with self.assertRaises(EconomyError):
                    self.db.finish_uno_game("table", winners, participants)
                self.assertEqual(self.balances(), [990, 990, 990])
        with self.assertRaises(EconomyError):
            self.db.reserve_bet(1, "slots", 10)
        self.assertEqual(self.db.finish_uno_game("table", [1])["status"], "settled")

    def test_cancellation_refunds_once_even_after_a_late_finish(self):
        self.db.start_uno_game("cancel", [1, 2, 3], 100)
        receipt = self.db.cancel_uno_game("cancel")
        self.assertEqual(receipt["status"], "refunded")
        self.assertEqual(receipt["refunds"], {1: 100, 2: 100, 3: 100})
        self.assertEqual(receipt["rewards"], {})
        self.assertEqual(self.db.cancel_uno_game("cancel"), receipt)
        self.assertEqual(self.db.finish_uno_game("cancel", [1]), receipt)
        self.assertEqual(self.balances(), [1000, 1000, 1000])

    def test_restart_refunds_active_games_once_and_releases_players(self):
        self.db.start_uno_game("staked", [1, 2], 100)
        self.db.start_uno_game("casual", [3, 4], 0)
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.db.recover_uno_games(), 2)
        self.assertEqual(self.db.recover_uno_games(), 0)
        self.assertEqual(self.balances((1, 2, 3, 4)), [1000] * 4)
        self.assertEqual(self.db.finish_uno_game("staked", [1])["status"], "refunded")
        self.assertEqual(self.db.finish_uno_game("casual", [3])["status"], "refunded")
        self.db.start_uno_game("new", [1, 2], 10)
        self.db.reserve_bet(3, "blackjack", 10)

    def test_uno_and_other_bets_block_each_other_including_casual_games(self):
        bet = self.db.reserve_bet(2, "slots", 1)
        with self.assertRaises(EconomyError):
            self.db.start_uno_game("table", [1, 2], 0)
        self.assertEqual(self.balances(), [1000, 999, 1000])
        self.db.settle_bet(bet)
        self.db.start_uno_game("table", [1, 2], 0)
        with self.assertRaises(EconomyError):
            self.db.start_uno_game("overlap", [2, 3], 0)
        with self.assertRaises(EconomyError):
            self.db.reserve_bet(1, "mines", 1)
        self.db.cancel_uno_game("table")
        self.db.reserve_bet(1, "mines", 1)

    def test_concurrent_overlapping_tables_reserve_only_once(self):
        def reserve(index):
            try:
                return self.db.start_uno_game(f"table-{index}", [1, 2], 600)
            except EconomyError:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, range(8)))
        self.assertEqual(len([result for result in results if result]), 1)
        self.assertEqual(self.balances(), [400, 400, 1000])
        self.assertEqual(self.db.recover_uno_games(), 1)
        self.assertEqual(self.balances(), [1000, 1000, 1000])

    def test_concurrent_uno_and_other_bet_cannot_both_start(self):
        def reserve(kind):
            try:
                if kind == "uno":
                    return self.db.start_uno_game("table", [1, 2], 100)
                return self.db.reserve_bet(1, "slots", 100)
            except EconomyError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ["uno", "slots"]))
        self.assertEqual(len([result for result in results if result]), 1)
        self.assertEqual(self.db.balance(1), 900)
        self.assertEqual(self.db.recover_bets() + self.db.recover_uno_games(), 1)
        self.assertEqual(self.balances(), [1000, 1000, 1000])

    def test_concurrent_finish_and_cancel_cannot_pay_twice(self):
        self.db.start_uno_game("table", [1, 2, 3], 100)

        def settle(index):
            if index % 2:
                return self.db.cancel_uno_game("table")
            return self.db.finish_uno_game("table", [1])

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(settle, range(12)))
        self.assertTrue(all(result == results[0] for result in results))
        if results[0]["status"] == "settled":
            self.assertEqual(self.balances(), [1235, 905, 905])
        else:
            self.assertEqual(self.balances(), [1000, 1000, 1000])

    def test_failure_mid_settlement_rolls_back_every_wallet_and_receipt(self):
        self.db.start_uno_game("table", [1, 2, 3], 100)
        original_user = self.db.user

        def failing_user(session, player_id):
            if player_id == 3:
                raise RuntimeError("simulated interrupted settlement")
            return original_user(session, player_id)

        with patch.object(self.db, "user", side_effect=failing_user):
            with self.assertRaises(RuntimeError):
                self.db.finish_uno_game("table", [1])
        self.assertEqual(self.balances(), [900, 900, 900])
        receipt = self.db.finish_uno_game("table", [1])
        self.assertEqual(receipt["status"], "settled")
        self.assertEqual(self.balances(), [1235, 905, 905])

    def test_large_stakes_and_winnings_keep_every_coin_across_restart(self):
        huge = 10 ** 40 + 3
        for player_id in (1, 2, 3):
            self.db.set_balance(player_id, 1)
            bet = self.db.reserve_bet(player_id, "slots", 1)
            self.db.settle_bet(bet, huge)
        self.db.start_uno_game("large", [1, 2, 3], huge)
        self.assertEqual(self.balances(), [0, 0, 0])
        receipt = self.db.finish_uno_game("large", [1, 2])
        self.assertEqual(sum(receipt["payouts"].values()), huge * 3)
        self.assertEqual(self.balances(), [(huge * 3 + 1) // 2 + 35,
                                          huge * 3 // 2 + 5, 5])
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.db.finish_uno_game("large", [1, 2]), receipt)
        self.assertEqual(sum(self.balances()), huge * 3 + 45)

    def test_unknown_table_is_not_created_by_finish_or_cancel(self):
        with self.assertRaises(EconomyError):
            self.db.finish_uno_game("unknown", [1])
        with self.assertRaises(EconomyError):
            self.db.cancel_uno_game("unknown")
        self.assertEqual(self.balances(), [1000, 1000, 1000])


if __name__ == "__main__":
    unittest.main()
