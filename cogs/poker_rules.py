"""No-limit Texas Hold'em: integer chips, private cards and independent rules."""
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
import random

SUITS = ("clubs", "diamonds", "hearts", "spades")
SYMBOLS = dict(zip(SUITS, "♣♦♥♠"))
HAND_NAMES = ("Carta alta", "Um par", "Dois pares", "Trinca", "Sequência",
              "Flush", "Full house", "Quadra", "Straight flush")
STREETS = {"preflop": "Pré-flop", "flop": "Flop", "turn": "Turn", "river": "River",
           "showdown": "Showdown", "finished": "Fim da mão"}


class PokerError(ValueError):
    pass


@dataclass(frozen=True)
class Card:
    rank: int
    suit: str

    @property
    def filename(self):
        rank = {11: "jack", 12: "queen", 13: "king", 14: "ace"}.get(self.rank, str(self.rank))
        return f"{rank}_of_{self.suit}.png"

    def __str__(self):
        return f"{dict(zip(range(11, 15), 'JQKA')).get(self.rank, self.rank)}{SYMBOLS[self.suit]}"


def full_deck():
    return [Card(rank, suit) for suit in SUITS for rank in range(2, 15)]


def rank_five(cards):
    counts = Counter(card.rank for card in cards)
    groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    ranks = sorted(counts, reverse=True)
    flush = len({card.suit for card in cards}) == 1
    straight = (5 if ranks == [14, 5, 4, 3, 2] else ranks[0]
                if len(ranks) == 5 and ranks[0] - ranks[-1] == 4 else 0)
    if flush and straight:
        return (8, straight)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if [group[0] for group in groups] == [3, 2]:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *ranks)
    if straight:
        return (4, straight)
    if groups[0][0] == 3:
        return (3, groups[0][1], *sorted((r for r in ranks if r != groups[0][1]), reverse=True))
    pairs = sorted((rank for count, rank in groups if count == 2), reverse=True)
    if len(pairs) == 2:
        return (2, *pairs, next(rank for rank in ranks if rank not in pairs))
    if pairs:
        return (1, pairs[0], *(rank for rank in ranks if rank != pairs[0]))
    return (0, *ranks)


def best_hand(cards):
    if not 5 <= len(cards) <= 7:
        raise PokerError("Uma mão precisa de 5 a 7 cartas para ser avaliada.")
    return max(rank_five(hand) for hand in combinations(cards, 5))


@dataclass
class Player:
    id: int
    name: str
    stack: int
    bot: bool = False
    cards: list = field(default_factory=list)
    folded: bool = False
    committed: int = 0
    street_bet: int = 0
    last_action: str = ""


class Holdem:
    def __init__(self, players, *, button=0, small_blind=1, rng=None, deck=None):
        if not 2 <= len(players) <= 6 or len({p.id for p in players}) != len(players):
            raise PokerError("A mesa precisa de 2 a 6 jogadores distintos.")
        if type(small_blind) is not int or small_blind < 1 or any(
                type(p.stack) is not int or p.stack <= 0 for p in players):
            raise PokerError("As fichas e os blinds devem ser inteiros positivos.")
        self.players = players
        self.button = button % len(players)
        self.small_blind, self.big_blind = small_blind, small_blind * 2
        self.rng = rng or random.SystemRandom()
        self.deck = list(deck) if deck is not None else full_deck()
        if len(self.deck) != 52 or set(self.deck) != set(full_deck()):
            raise PokerError("O baralho precisa conter as 52 cartas, sem repetições.")
        if deck is None:
            self.rng.shuffle(self.deck)
        self.board, self.burned, self.log = [], [], []
        self.street, self.done, self.showdown = "preflop", False, False
        self.revision, self.payouts, self.pots = 0, {}, []
        self.initial_total = sum(p.stack for p in players)
        self.current_bet = self.big_blind
        self.last_raise = self.big_blind
        self.acted_at = {}
        for _ in range(2):
            for offset in range(1, len(players) + 1):
                players[(self.button + offset) % len(players)].cards.append(self.deck.pop())
        self.sb_index = self.button if len(players) == 2 else (self.button + 1) % len(players)
        self.bb_index = (self.sb_index + 1) % len(players)
        for index, amount, label in ((self.sb_index, small_blind, "Small blind"),
                                      (self.bb_index, self.big_blind, "Big blind")):
            self._commit(players[index], min(amount, players[index].stack))
            players[index].last_action = label
        self.pending = {p.id for p in players if p.stack}
        self.actor_index = self.bb_index
        self._advance()

    @property
    def actor(self):
        return None if self.done else self.players[self.actor_index]

    @property
    def pot(self):
        return sum(p.committed for p in self.players)

    def to_call(self, player):
        return max(0, self.current_bet - player.street_bet)

    @property
    def min_raise_to(self):
        return self.current_bet + self.last_raise

    def can_raise(self, player):
        return (any(p.id != player.id and not p.folded and p.stack for p in self.players)
                and player.stack + player.street_bet > self.current_bet
                and (player.id not in self.acted_at
                     or self.current_bet - self.acted_at[player.id] >= self.last_raise))

    @staticmethod
    def _commit(player, amount):
        player.stack -= amount
        player.committed += amount
        player.street_bet += amount

    def act(self, player_id, action, amount=None):
        if self.done or self.actor.id != player_id:
            raise PokerError("Não é a sua vez ou a mão já terminou.")
        player = self.actor
        if action == "allin":
            amount = player.street_bet + player.stack
            action = "raise" if amount > self.current_bet else "call"
        if action == "fold":
            player.folded, player.last_action = True, "Desistiu"
        elif action == "check":
            if self.to_call(player):
                raise PokerError("Há uma aposta para pagar; pague ou desista.")
            player.last_action = "Mesa"
        elif action == "call":
            paid = min(self.to_call(player), player.stack)
            self._commit(player, paid)
            player.last_action = f"Pagou {paid:,} D$" if paid else "Mesa"
        elif action == "raise":
            maximum = player.stack + player.street_bet
            if (type(amount) is not int or not self.current_bet < amount <= maximum
                    or not self.can_raise(player)):
                raise PokerError("Aumento inválido ou a aposta não foi reaberta para você.")
            increase = amount - self.current_bet
            if increase < self.last_raise and amount != maximum:
                raise PokerError(f"Aumente para pelo menos {self.min_raise_to:,} D$, ou use all-in.")
            self._commit(player, amount - player.street_bet)
            if increase >= self.last_raise:
                self.last_raise = increase
            self.current_bet = amount
            self.pending.update(p.id for p in self.players if not p.folded and p.stack
                                and p.street_bet < amount)
            player.last_action = f"Aumentou para {amount:,} D$"
        else:
            raise PokerError("Ação desconhecida.")
        if not player.stack and not player.folded:
            player.last_action += " · All-in"
        self.log.append(f"{player.name}: {player.last_action}")
        self.acted_at[player.id] = self.current_bet
        self.pending.discard(player.id)
        self.revision += 1
        self._advance()

    def _advance(self):
        while True:
            live = [p for p in self.players if not p.folded]
            if len(live) == 1:
                self.payouts = {p.id: self.pot if p == live[0] else 0 for p in self.players}
                self.pots = [(self.pot, [live[0].id])]
                self._finish()
                return
            able = [p for p in live if p.stack]
            self.pending.intersection_update(p.id for p in able)
            # A lone funded player only acts if still facing an outstanding bet.
            if len(able) == 1 and not self.to_call(able[0]):
                self.pending.clear()
            if self.pending:
                for offset in range(1, len(self.players) + 1):
                    index = (self.actor_index + offset) % len(self.players)
                    if self.players[index].id in self.pending:
                        self.actor_index = index
                        return
            if self.street == "river":
                self._showdown()
                return
            self.burned.append(self.deck.pop())
            count = 3 if self.street == "preflop" else 1
            self.board.extend(self.deck.pop() for _ in range(count))
            self.street = {"preflop": "flop", "flop": "turn", "turn": "river"}[self.street]
            self.current_bet, self.last_raise = 0, self.big_blind
            self.acted_at.clear()
            for player in self.players:
                player.street_bet = 0
            self.pending = {p.id for p in able} if len(able) >= 2 else set()
            self.actor_index = self.button

    def _showdown(self):
        self.showdown = True
        self.payouts = {p.id: 0 for p in self.players}
        scores = {p.id: best_hand(p.cards + self.board) for p in self.players if not p.folded}
        previous = 0
        for level in sorted({p.committed for p in self.players if p.committed}):
            contributors = [p for p in self.players if p.committed >= level]
            amount = (level - previous) * len(contributors)
            previous = level
            if len(contributors) == 1:
                # An unmatched bet returns to its owner without becoming a side pot.
                self.payouts[contributors[0].id] += amount
                continue
            eligible = [p for p in contributors if not p.folded]
            score = max(scores[p.id] for p in eligible)
            winners = {p.id for p in eligible if scores[p.id] == score}
            order = [self.players[(self.button + offset) % len(self.players)].id
                     for offset in range(1, len(self.players) + 1)]
            winners = [pid for pid in order if pid in winners]
            share, remainder = divmod(amount, len(winners))
            for index, pid in enumerate(winners):
                self.payouts[pid] += share + int(index < remainder)
            self.pots.append((amount, winners))
        self._finish()

    def _finish(self):
        for player in self.players:
            player.stack += self.payouts.get(player.id, 0)
        self.done, self.street = True, "showdown" if self.showdown else "finished"
        self.pending.clear()
        assert sum(p.stack for p in self.players) == self.initial_total


def bot_decision(hole, board, *, opponents, stack, street_bet, to_call, pot,
                 minimum, can_raise, rng=None, samples=36):
    """Estimate equity using ONLY this bot's cards and public information."""
    rng = rng or random.SystemRandom()
    unknown = [card for card in full_deck() if card not in (*hole, *board)]
    equity = 0.0
    for _ in range(samples):
        drawn = rng.sample(unknown, 5 - len(board) + 2 * opponents)
        community = list(board) + drawn[:5 - len(board)]
        opponents_cards = drawn[5 - len(board):]
        own = best_hand(list(hole) + community)
        scores = [best_hand(opponents_cards[i * 2:i * 2 + 2] + community)
                  for i in range(opponents)]
        if own >= max(scores):
            equity += 1 / (1 + scores.count(own))
    equity /= samples
    call = min(stack, to_call)
    odds = call / max(1, pot + call)
    if to_call and equity + rng.uniform(-0.06, 0.09) < odds:
        return "fold", None
    if can_raise and (equity > 0.60 or rng.random() < 0.06):
        target = min(stack + street_bet, max(minimum, street_bet + to_call + max(1, pot // 2)))
        return "raise", target
    return ("call" if to_call else "check"), None
