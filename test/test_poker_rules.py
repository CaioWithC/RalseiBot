"""Poker ranking, betting order, all-in boundaries and conservation of chips."""
import random
import unittest

from cogs.poker_rules import Card, Holdem, Player, PokerError, best_hand, full_deck, bot_decision


def cards(text):
    return [Card("23456789TJQKA".index(value[0]) + 2,
                 {"c": "clubs", "d": "diamonds", "h": "hearts", "s": "spades"}[value[1]])
            for value in text.split()]


def rigged(hands, board, button=0):
    hands = [cards(hand) for hand in hands]
    board = cards(board)
    unused = [card for card in full_deck() if card not in board and all(card not in hand for hand in hands)]
    deal = [hands[(button + offset) % len(hands)][index] for index in range(2)
            for offset in range(1, len(hands) + 1)]
    deal += [unused.pop(), *board[:3], unused.pop(), board[3], unused.pop(), board[4]]
    return list(reversed(deal + unused))


def players(stacks):
    return [Player(i + 1, f"Player {i + 1}", stack) for i, stack in enumerate(stacks)]


class PokerRulesTests(unittest.TestCase):
    def test_hand_categories_are_ordered_and_use_best_five_of_seven(self):
        hands = ["As Jd 9h 7c 3d", "As Ad Qc 8h 3d", "As Ad Qc Qh 3d",
                 "As Ad Ac 8h 3d", "2s 3d 4c 5h 6d", "As Js 9s 7s 3s",
                 "As Ad Ac 8h 8d", "As Ad Ac Ah 3d", "Ts Js Qs Ks As"]
        ranks = [best_hand(cards(hand)) for hand in hands]
        self.assertEqual([rank[0] for rank in ranks], list(range(9)))
        self.assertEqual(sorted(ranks), ranks)
        self.assertEqual(best_hand(cards("As Ad Ac Kh Kd Kc 2s")), (6, 14, 13))
        self.assertEqual(best_hand(cards("As 2s 3s 4s 5s 7h 8d")), (8, 5))
        self.assertGreater(best_hand(cards("As Ad Kc 8h 3d")), best_hand(cards("Ah Ac Qd Js 9h")))

    def test_deck_and_deal_have_no_duplicate_cards(self):
        game = Holdem(players([100] * 6), rng=random.Random(4))
        seen = game.deck + [card for p in game.players for card in p.cards]
        self.assertEqual(len(seen), 52)
        self.assertEqual(set(seen), set(full_deck()))

    def test_heads_up_button_posts_small_blind_and_acts_first_only_preflop(self):
        game = Holdem(players([100, 100]), button=0, small_blind=5)
        self.assertEqual((game.sb_index, game.bb_index, game.actor.id), (0, 1, 1))
        game.act(1, "call")
        self.assertEqual(game.actor.id, 2)
        game.act(2, "check")
        self.assertEqual((game.street, game.actor.id, len(game.board)), ("flop", 2, 3))
        self.assertEqual(len(game.burned), 1)
        for _ in range(6):
            game.act(game.actor.id, "check")
        self.assertTrue(game.done)
        self.assertEqual((len(game.board), len(game.burned)), (5, 3))

    def test_invalid_and_out_of_turn_actions_do_not_mutate_chips(self):
        game = Holdem(players([100] * 3), small_blind=5)
        before = [(p.stack, p.committed, p.folded) for p in game.players]
        for pid, action, amount in [(2, "call", None), (1, "check", None), (1, "raise", 15),
                                     (1, "raise", 101), (1, "raise", True), (1, "fake", None)]:
            with self.assertRaises(PokerError):
                game.act(pid, action, amount)
            self.assertEqual([(p.stack, p.committed, p.folded) for p in game.players], before)
            self.assertEqual(game.revision, 0)

    def test_big_blind_gets_option_to_raise_after_everyone_calls(self):
        game = Holdem(players([100] * 3), small_blind=5)
        game.act(1, "call")
        game.act(2, "call")
        self.assertEqual((game.street, game.actor.id), ("preflop", 3))
        game.act(3, "raise", 25)
        self.assertEqual(game.min_raise_to, 40)
        game.act(1, "call")
        game.act(2, "call")
        self.assertEqual(game.street, "flop")

    def test_short_allin_does_not_reopen_betting_for_player_who_already_acted(self):
        game = Holdem(players([100, 25, 100]), small_blind=5)
        game.act(1, "raise", 20)
        game.act(2, "allin")
        self.assertEqual(game.current_bet, 25)
        self.assertFalse(game.can_raise(game.players[0]))
        self.assertTrue(game.can_raise(game.players[2]))
        game.act(3, "call")
        with self.assertRaises(PokerError):
            game.act(1, "raise", 35)
        game.act(1, "call")
        self.assertEqual(game.street, "flop")

    def test_cumulative_short_allins_reopen_a_full_raise(self):
        game = Holdem(players([25, 30, 100, 100]), button=0, small_blind=5)
        game.act(4, "raise", 20)
        game.act(1, "allin")
        game.act(2, "allin")
        game.act(3, "call")
        self.assertEqual(game.actor.id, 4)
        self.assertTrue(game.can_raise(game.actor))
        game.act(4, "raise", 40)
        self.assertEqual(game.current_bet, 40)

    def test_allin_side_pots_only_pay_eligible_players(self):
        deck = rigged(["Ac Ad", "Kc Kd", "Qc Qd"], "2h 3s 7h 8d 9c")
        game = Holdem(players([20, 50, 100]), deck=deck)
        game.act(1, "allin")
        game.act(2, "allin")
        game.act(3, "call")
        self.assertTrue(game.done)
        self.assertEqual(game.pots, [(60, [1]), (60, [2])])
        self.assertEqual([p.stack for p in game.players], [60, 60, 50])

    def test_uncalled_excess_returns_even_when_another_player_wins(self):
        deck = rigged(["Qc Qd", "Ac Ad", "Kc Kd"], "2h 3s 7h 8d 9c")
        game = Holdem(players([100, 20, 50]), deck=deck)
        game.act(1, "allin")
        game.act(2, "call")
        game.act(3, "call")
        self.assertEqual([p.stack for p in game.players], [50, 60, 60])
        self.assertEqual(sum(game.payouts.values()), 170)

    def test_folded_contributions_and_tied_board_split_with_odd_chip_after_button(self):
        deck = rigged(["2c 3c", "4d 5d", "6h 7h"], "Ts Js Qs Ks As")
        game = Holdem(players([100] * 3), deck=deck, small_blind=1)
        game.act(1, "call")
        game.act(2, "fold")
        game.act(3, "check")
        while not game.done:
            game.act(game.actor.id, "check")
        self.assertEqual(game.payouts, {1: 2, 2: 0, 3: 3})
        self.assertEqual([p.stack for p in game.players], [100, 99, 101])

    def test_fold_win_does_not_expose_or_deal_remaining_cards(self):
        game = Holdem(players([100, 100]), small_blind=5)
        game.act(1, "fold")
        self.assertTrue(game.done)
        self.assertFalse(game.showdown)
        self.assertEqual(game.board, [])
        self.assertEqual([p.stack for p in game.players], [95, 105])

    def test_random_legal_games_always_terminate_and_conserve_chips(self):
        rng = random.Random(83)
        for iteration in range(250):
            stacks = [rng.randint(1, 400) for _ in range(rng.randint(2, 6))]
            game = Holdem(players(stacks), small_blind=rng.randint(1, 10), rng=rng)
            for _ in range(250):
                if game.done:
                    break
                player = game.actor
                actions = ["call" if game.to_call(player) else "check", "fold"]
                if game.can_raise(player):
                    actions += ["allin", "raise"]
                action = rng.choice(actions)
                amount = min(player.stack + player.street_bet, game.min_raise_to) if action == "raise" else None
                game.act(player.id, action, amount)
                self.assertTrue(all(p.stack >= 0 for p in game.players))
            self.assertTrue(game.done, iteration)
            self.assertEqual(sum(p.stack for p in game.players), sum(stacks))

    def test_bot_can_play_using_only_its_own_cards_and_public_values(self):
        action, amount = bot_decision(cards("As Ad"), cards("Ac Ah 2s 3s 4d"), opponents=4,
            stack=100, street_bet=0, to_call=10, pot=50, minimum=20, can_raise=True,
            rng=random.Random(1), samples=10)
        self.assertEqual(action, "raise")
        self.assertTrue(20 <= amount <= 100)


if __name__ == "__main__":
    unittest.main()
