"""Offline behavior tests for the Six rules and adversarial stale actions."""
import copy
import random
import unittest

from cogs.uno_rules import Card, RuleError, Rules, UnoGame


class UnoRulesTests(unittest.TestCase):
    def setUp(self):
        self.serial = 0

    def card(self, color, value):
        self.serial += 1
        return Card(str(self.serial), color, str(value))

    def game(self, hands=None, rules=None, winner_count=1):
        hands = hands or {1: [("red", 3), ("blue", 4)], 2: [("blue", 1), ("green", 2)], 3: [("yellow", 1), ("green", 4)]}
        game = UnoGame(list(hands), rules=rules, winner_count=winner_count, rng=random.Random(1), now=0)
        game.hands = {player: [self.card(*spec) for spec in specs] for player, specs in hands.items()}
        game.discard_pile = [self.card("red", 5)]
        game.current_color = "red"
        game.draw_pile = [self.card("blue", 8) for _ in range(40)]
        return game

    def play(self, game, player, index=0, **kwargs):
        game.play(player, [game.hands[player][index].uid], now=kwargs.pop("now", 1), **kwargs)

    def assert_rejected_unchanged(self, game, operation):
        before = copy.deepcopy(game.__dict__)
        rng_state = before.pop("rng").getstate()
        with self.assertRaises(RuleError):
            operation()
        after = dict(game.__dict__)
        self.assertEqual(after.pop("rng").getstate(), rng_state)
        self.assertEqual(before, after)

    def test_deals_unique_cards_for_all_table_sizes_and_seeds(self):
        for count in range(2, 21):
            for seed in range(10):
                game = UnoGame(range(1, count + 1), rng=random.Random(seed), now=0)
                self.assertTrue(all(len(hand) == 7 for hand in game.hands.values()))
                cards = [card for hand in game.hands.values() for card in hand] + game.draw_pile + game.discard_pile
                self.assertEqual(len(cards), 108 if count <= 15 else 216)
                self.assertEqual(len({card.uid for card in cards}), len(cards))
                self.assertIn(game.top.value, {str(value) for value in range(10)})
                self.assertEqual(game.turn_deadline, 60)

    def test_invalid_tables(self):
        for players, winners in (([1], 1), ([1, 1], 1), (range(21), 1), ([1, 2], 2), ([1, 2], 0)):
            with self.assertRaises(RuleError):
                UnoGame(players, winner_count=winners)

    def test_matching_color_value_and_wildcards(self):
        game = self.game({1: [("red", 3), ("blue", 5), ("green", 8), (None, "wild"), (None, "wild4")], 2: [("red", 1)]})
        self.assertEqual([card.value for card in game.legal_cards(1)], ["3", "5", "wild", "wild4"])
        self.assertEqual(game.legal_cards(2), [])
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1, 2))
        self.play(game, 1, 1)
        self.assertEqual(game.current_color, "blue")
        self.assertEqual(game.current_player, 2)
        self.assertEqual(game.revision, 1)

    def test_rejects_wrong_player_missing_duplicate_and_stale_cards(self):
        game = self.game()
        self.assert_rejected_unchanged(game, lambda: self.play(game, 2))
        self.assert_rejected_unchanged(game, lambda: game.play(1, ["missing"], now=1))
        card_id = game.hands[1][0].uid
        self.assert_rejected_unchanged(game, lambda: game.play(1, [card_id, card_id], now=1))
        self.assert_rejected_unchanged(game, lambda: game.play(1, None, now=1))
        self.play(game, 1)
        self.assert_rejected_unchanged(game, lambda: game.play(1, [card_id], now=1))

    def test_wild_color_selection_is_required_and_atomic(self):
        game = self.game({1: [(None, "wild"), ("red", 3)], 2: [("red", 1)]})
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1))
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1, color="purple"))
        self.play(game, 1, color="green")
        self.assertEqual(game.current_color, "green")

    def test_reverse_and_skip_with_three_players(self):
        for value in ("reverse", "skip"):
            game = self.game()
            game.hands[1][0] = self.card("red", value)
            self.play(game, 1)
            self.assertEqual(game.current_player, 3)
            self.assertEqual(game.direction, -1 if value == "reverse" else 1)

    def test_reverse_and_skip_with_two_players_give_another_turn(self):
        for value in ("reverse", "skip"):
            game = self.game({1: [("red", value), ("red", 3)], 2: [("red", 1)]})
            self.play(game, 1)
            self.assertEqual(game.current_player, 1)
            self.assertEqual(game.turn_deadline, 61)

    def test_draw_penalty_without_stacking_blocks_play_then_skips(self):
        game = self.game({1: [("red", "draw2"), ("red", 1)], 2: [("blue", "draw2"), ("red", 1)], 3: [("red", 1)]})
        self.play(game, 1)
        self.assertEqual(game.pending_draw, 2)
        self.assertEqual(game.legal_cards(2), [])
        self.assert_rejected_unchanged(game, lambda: self.play(game, 2, now=2))
        game.draw(2, now=2)
        self.assertEqual(len(game.hands[2]), 4)
        self.assertEqual(game.pending_draw, 0)
        self.assertEqual(game.current_player, 3)

    def test_any_draw_two_or_four_stacks_regardless_of_color(self):
        game = self.game({1: [("red", "draw2"), ("red", 1)], 2: [(None, "wild4"), ("green", 2)], 3: [("blue", "draw2"), ("red", 1)]}, Rules(stack_draw=True))
        self.play(game, 1)
        self.play(game, 2, color="yellow", now=2)
        self.assertEqual(game.pending_draw, 6)
        self.assertEqual(game.challenge.previous_draw, 2)
        self.play(game, 3, now=3)
        self.assertEqual(game.pending_draw, 8)
        self.assertIsNone(game.challenge)
        game.draw(1, now=4)
        self.assertEqual(len(game.hands[1]), 9)
        self.assertEqual(game.current_player, 2)

    def test_successful_draw_four_challenge_penalizes_offender_and_keeps_turn(self):
        game = self.game({1: [(None, "wild4"), ("red", 3)], 2: [("blue", 1)], 3: [("green", 4)]})
        self.play(game, 1, color="blue")
        self.assertTrue(game.challenge.illegal)
        game.challenge_draw_four(2, now=2)
        self.assertEqual(len(game.hands[1]), 5)
        self.assertEqual(len(game.hands[2]), 1)
        self.assertEqual(game.current_player, 2)
        self.assertEqual(game.pending_draw, 0)
        self.assertIsNone(game.challenge)
        self.assertIn("Blefe", game.last_action)

    def test_failed_draw_four_challenge_draws_six_and_skips(self):
        game = self.game({1: [(None, "wild4"), ("green", 3)], 2: [("blue", 1)], 3: [("green", 4)]})
        self.play(game, 1, color="blue")
        game.challenge_draw_four(2, now=2)
        self.assertEqual(len(game.hands[2]), 7)
        self.assertEqual(game.current_player, 3)
        self.assertEqual(game.pending_draw, 0)

    def test_successful_stacked_challenge_preserves_previous_debt(self):
        game = self.game({1: [("red", "draw2"), ("red", 1)], 2: [(None, "wild4"), ("red", 3)], 3: [("blue", 1)]}, Rules(stack_draw=True))
        self.play(game, 1)
        self.play(game, 2, color="blue", now=2)
        game.challenge_draw_four(3, now=3)
        self.assertEqual(game.pending_draw, 2)
        self.assertEqual(game.current_player, 3)
        game.draw(3, now=4)
        self.assertEqual(len(game.hands[3]), 3)

    def test_disabled_challenge_forbids_illegal_four(self):
        game = self.game({1: [(None, "wild4"), ("red", 3)], 2: [("blue", 1)]}, Rules(challenge_draw4=False))
        self.assertNotIn(game.hands[1][0], game.legal_cards(1))
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1, color="blue"))
        game.hands[1][1] = self.card("green", 3)
        self.play(game, 1, color="blue")
        self.assertIsNone(game.challenge)
        self.assert_rejected_unchanged(game, lambda: game.challenge_draw_four(2, now=2))

    def test_last_draw_four_waits_for_challenge_before_awarding_winner(self):
        game = self.game({1: [(None, "wild4")], 2: [("blue", 1)], 3: [("green", 4)]})
        self.play(game, 1, color="blue")
        self.assertFalse(game.finished)
        self.assertEqual(game.winners, [])
        self.assertIn(1, game.players)
        game.challenge_draw_four(2, now=2)
        self.assertTrue(game.finished)
        self.assertEqual(game.winners, [1])
        self.assertEqual(len(game.hands[2]), 7)

    def test_last_four_accepted_by_drawing_or_timeout_awards_winner(self):
        for timeout in (False, True):
            game = self.game({1: [(None, "wild4")], 2: [("blue", 1)]})
            self.play(game, 1, color="blue")
            if timeout:
                game.timeout(now=61)
            else:
                game.draw(2, now=2)
            self.assertTrue(game.finished)
            self.assertEqual(game.winners, [1])
            self.assertEqual(len(game.hands[2]), 5)

    def test_multiple_number_cards_must_match(self):
        game = self.game({1: [("red", 3), ("blue", 3), ("green", 1)], 2: [("red", 1)]}, Rules(multiple_cards=True))
        self.assert_rejected_unchanged(game, lambda: game.play(1, [game.hands[1][0].uid, game.hands[1][2].uid], now=1))
        game.play(1, [card.uid for card in game.hands[1][:2]], now=1)
        self.assertEqual(len(game.hands[1]), 1)
        self.assertEqual(game.current_color, "blue")
        self.assertEqual(game.top.value, "3")

    def test_multiple_selection_accepts_matching_card_in_any_position(self):
        game = self.game({1: [("blue", 3), ("red", 3), ("green", 1)], 2: [("red", 1)]}, Rules(multiple_cards=True))
        game.play(1, [card.uid for card in game.hands[1][:2]], now=1)
        self.assertEqual(len(game.hands[1]), 1)
        self.assertEqual(game.current_color, "blue")
        self.assertEqual([card.color for card in game.discard_pile[-2:]], ["red", "blue"])

    def test_multiple_action_cards_and_disabled_multiple_are_rejected(self):
        for enabled, value in ((False, "3"), (True, "skip")):
            game = self.game({1: [("red", value), ("red", value)], 2: [("red", 1)]}, Rules(multiple_cards=enabled))
            self.assert_rejected_unchanged(game, lambda: game.play(1, [card.uid for card in game.hands[1]], now=1))

    def test_draw_unplayable_automatically_passes(self):
        game = self.game()
        game.draw(1, now=1)
        self.assertEqual(len(game.hands[1]), 3)
        self.assertEqual(game.current_player, 2)
        self.assertFalse(game.can_pass(1))

    def test_draw_playable_allows_only_new_card_or_pass(self):
        game = self.game()
        game.draw_pile.append(self.card("red", 7))
        game.draw(1, now=1)
        self.assertEqual(game.current_player, 1)
        self.assertTrue(game.can_pass(1))
        self.assertFalse(game.can_draw(1))
        self.assertEqual(game.turn_deadline, 60)
        self.assertEqual(game.legal_cards(1), [game.hands[1][-1]])
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1, now=2))
        self.assert_rejected_unchanged(game, lambda: game.draw(1, now=2))
        game.pass_turn(1, now=2)
        self.assertEqual(game.current_player, 2)
        self.assertIsNone(game.drawn_player)

    def test_drawn_card_can_be_played(self):
        game = self.game()
        game.draw_pile.append(self.card("red", 7))
        game.draw(1, now=1)
        self.play(game, 1, -1, now=2)
        self.assertEqual(game.top.value, "7")
        self.assertEqual(len(game.hands[1]), 2)

    def test_draw_until_playable_stops_at_first_matching_card(self):
        game = self.game(rules=Rules(draw_until_playable=True))
        game.draw_pile = [self.card("green", 2), self.card("red", 9), self.card("blue", 8), self.card("green", 7)]
        game.draw(1, now=1)
        self.assertEqual(len(game.hands[1]), 5)
        self.assertEqual(game.current_player, 1)
        self.assertEqual([card.value for card in game.legal_cards(1)], ["9"])
        self.assertEqual(len(game.draw_pile), 1)

    def test_pass_before_draw_rejected(self):
        game = self.game()
        self.assert_rejected_unchanged(game, lambda: game.pass_turn(1, now=1))

    def test_three_second_uno_window_and_exactly_once_catch(self):
        game = self.game()
        self.play(game, 1, now=1)
        self.assertEqual(game.uno_pending[1], 4)
        self.assert_rejected_unchanged(game, lambda: game.catch_uno(2, 1, now=3.99))
        self.assert_rejected_unchanged(game, lambda: game.call_uno(1, now=4))
        self.assert_rejected_unchanged(game, lambda: game.catch_uno(1, 1, now=4))
        game.catch_uno(2, 1, now=4)
        self.assertEqual(len(game.hands[1]), 3)
        self.assertEqual(game.current_player, 2)
        self.assertEqual(game.turn_deadline, 61)
        self.assert_rejected_unchanged(game, lambda: game.catch_uno(3, 1, now=4))

    def test_call_during_window_and_predeclare_protect_player(self):
        for predeclare in (False, True):
            game = self.game()
            self.play(game, 1, declare_uno=predeclare, now=1)
            if not predeclare:
                game.call_uno(1, now=3.99)
            self.assertIn(1, game.uno_called)
            self.assertNotIn(1, game.uno_pending)
            self.assert_rejected_unchanged(game, lambda: game.catch_uno(2, 1, now=4))

    def test_next_game_action_closes_uno_catch_opportunity(self):
        game = self.game()
        self.play(game, 1, now=1)
        game.draw(2, now=5)
        self.assert_rejected_unchanged(game, lambda: game.catch_uno(3, 1, now=5))

    def test_fast_next_action_preserves_full_three_second_call_window(self):
        game = self.game()
        self.play(game, 1, now=1)
        game.draw(2, now=2)
        self.assertEqual(game.uno_pending[1], 4)
        game.call_uno(1, now=3.99)
        self.assertIn(1, game.uno_called)

    def test_timeout_takes_one_and_moves_exactly_once(self):
        game = self.game()
        self.assertFalse(game.timeout(now=59.99))
        self.assertEqual(game.revision, 0)
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1, now=60))
        self.assertTrue(game.timeout(now=60))
        self.assertEqual(len(game.hands[1]), 3)
        self.assertEqual(game.current_player, 2)
        self.assertFalse(game.timeout(now=60))
        self.assertEqual(game.revision, 1)

    def test_recycle_preserves_top_card_and_all_card_identities(self):
        game = self.game()
        recycled = [self.card("blue", 2), self.card("green", 4)]
        top = game.top
        game.discard_pile = [*recycled, top]
        game.draw_pile = []
        game.draw(1, now=1)
        self.assertIs(game.top, top)
        self.assertEqual(len(game.discard_pile), 1)
        self.assertEqual({card.uid for card in game.draw_pile + game.hands[1][2:]}, {card.uid for card in recycled})

    def test_exhausted_deck_never_loops_or_duplicates(self):
        game = self.game(rules=Rules(draw_until_playable=True))
        game.draw_pile = []
        game.draw(1, now=1)
        self.assertEqual(len(game.hands[1]), 2)
        self.assertEqual(game.current_player, 2)
        self.assertEqual(len(game.discard_pile), 1)

    def test_seven_swaps_hands_and_resets_uno(self):
        game = self.game({1: [("red", 7), ("blue", 2)], 2: [("red", 1)], 3: [("blue", 4)]}, Rules(seven_zero=True))
        game.uno_called.add(2)
        old_target = list(game.hands[2])
        old_remaining = game.hands[1][1]
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1))
        self.assert_rejected_unchanged(game, lambda: self.play(game, 1, target_id=1))
        self.play(game, 1, target_id=2, declare_uno=True)
        self.assertEqual(game.hands[1], old_target)
        self.assertEqual(game.hands[2], [old_remaining])
        self.assertEqual(game.uno_called, set())
        self.assertEqual(game.uno_pending, {1: 4, 2: 4})

    def test_terminal_draw_cards_apply_debt_before_final_result(self):
        for value, color, count in (("draw2", "red", 2), ("wild4", None, 4)):
            game = self.game({1: [(color, value)], 2: [("blue", 1)], 3: [("green", 2)]},
                             Rules(challenge_draw4=False))
            self.play(game, 1, color="red" if color is None else None)
            self.assertTrue(game.finished)
            self.assertEqual(game.winners, [1])
            self.assertEqual(len(game.hands[2]), 1 + count)
            self.assertEqual(game.pending_draw, 0)

    def test_nonterminal_winner_keeps_debt_for_next_player(self):
        game = self.game({1: [("red", "draw2")], 2: [("blue", 1)], 3: [("green", 2)]}, winner_count=2)
        self.play(game, 1)
        self.assertFalse(game.finished)
        self.assertEqual(game.pending_draw, 2)
        self.assertEqual(len(game.hands[2]), 1)

    def test_zero_rotates_hands_in_both_directions(self):
        for direction in (1, -1):
            game = self.game({1: [("red", 0), ("blue", 2)], 2: [("red", 1), ("green", 1)], 3: [("blue", 4), ("yellow", 2)]}, Rules(seven_zero=True))
            game.direction = direction
            previous = {player: list(hand) for player, hand in game.hands.items()}
            previous[1] = previous[1][1:]
            self.play(game, 1)
            for player in game.players:
                recipient = game.players[(game.players.index(player) + direction) % 3]
                self.assertEqual(game.hands[recipient], previous[player])

    def test_last_seven_transfers_empty_hand_to_target_winner(self):
        game = self.game({1: [("red", 7)], 2: [("red", 1), ("green", 1)], 3: [("blue", 4)]}, Rules(seven_zero=True))
        self.play(game, 1, target_id=2)
        self.assertEqual(game.winners, [2])
        self.assertEqual(len(game.hands[1]), 2)
        self.assertTrue(game.finished)

    def test_multiple_winners_leave_in_order_and_end_before_last_loser(self):
        game = self.game({1: [("red", 1)], 2: [("red", 2)], 3: [("red", 3)]}, winner_count=2)
        self.play(game, 1)
        self.assertEqual(game.winners, [1])
        self.assertEqual(game.players, [2, 3])
        self.assertEqual(game.current_player, 2)
        self.assertFalse(game.finished)
        self.play(game, 2, now=2)
        self.assertTrue(game.finished)
        self.assertEqual(game.winners, [1, 2])
        self.assertEqual(game.players, [3])
        self.assertIn("Partida encerrada", game.last_action)
        self.assert_rejected_unchanged(game, lambda: game.draw(3, now=3))
        self.assertFalse(game.timeout(now=100))

    def test_last_reverse_moves_turn_to_surviving_player(self):
        game = self.game({1: [("red", "reverse")], 2: [("red", 2)], 3: [("red", 3)]}, winner_count=2)
        self.play(game, 1)
        self.assertEqual(game.winners, [1])
        self.assertEqual(game.current_player, 3)
        self.assertEqual(game.direction, -1)

    def test_seeded_complete_games_preserve_every_card_and_turn_invariants(self):
        for seed in range(30):
            rng = random.Random(seed)
            count = rng.randint(2, 8)
            rules = Rules(*(rng.choice((False, True)) for _ in range(5)))
            game = UnoGame(range(1, count + 1), rules, winner_count=rng.randint(1, count - 1), rng=rng, now=0)
            original_ids = {card.uid for hand in game.hands.values() for card in hand} | {card.uid for card in game.draw_pile + game.discard_pile}
            for step in range(1, 2001):
                if game.finished:
                    break
                player = game.current_player
                legal = game.legal_cards(player)
                if game.challenge and rng.random() < 0.3:
                    game.challenge_draw_four(player, now=step)
                elif legal:
                    card = rng.choice(legal)
                    target = rng.choice([other for other in game.players if other != player])
                    game.play(player, [card.uid], color=rng.choice(("red", "yellow", "green", "blue")) if card.color is None else None,
                              target_id=target, declare_uno=True, now=step)
                elif game.can_pass(player):
                    game.pass_turn(player, now=step)
                else:
                    game.draw(player, now=step)
                all_cards = [card for hand in game.hands.values() for card in hand] + game.draw_pile + game.discard_pile
                self.assertEqual(len(all_cards), len(original_ids), (seed, step))
                self.assertEqual({card.uid for card in all_cards}, original_ids, (seed, step))
                self.assertIn(game.current_player, game.players, (seed, step))
                self.assertTrue(all(not game.hands[winner] for winner in game.winners))
                self.assertEqual(len(set(game.winners)), len(game.winners))
                self.assertGreaterEqual(game.pending_draw, 0)
            self.assertTrue(game.finished, f"Seed {seed} did not finish within 2000 actions")


if __name__ == "__main__":
    unittest.main()
