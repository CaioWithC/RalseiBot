"""Deterministic Six/Uno rules, independent from Discord and persistence.

Every public action validates its input before changing the game. Callers must
serialize actions for a table; ``revision`` can invalidate old Discord controls.
Times are monotonic seconds and can be supplied explicitly by tests.
"""
from dataclasses import dataclass
import math
import random
import time


COLORS = ("red", "yellow", "green", "blue")
TURN_SECONDS = 60
UNO_SECONDS = 3
NUMBER_VALUES = frozenset(str(number) for number in range(10))


class RuleError(ValueError):
    """A rejected action. Its message is safe to show to the player."""


@dataclass(frozen=True)
class Card:
    uid: str
    color: str | None
    value: str


@dataclass(frozen=True)
class Rules:
    challenge_draw4: bool = True
    stack_draw: bool = False
    multiple_cards: bool = False
    draw_until_playable: bool = False
    seven_zero: bool = False


@dataclass(frozen=True)
class DrawFourChallenge:
    offender: int
    challenger: int
    illegal: bool
    amount: int
    previous_draw: int = 0


class UnoGame:
    def __init__(self, player_ids, rules=None, winner_count=1, rng=None, now=None):
        players = list(player_ids)
        if not 2 <= len(players) <= 20 or len(set(players)) != len(players):
            raise RuleError("A mesa precisa de 2 a 20 jogadores diferentes.")
        if any(not isinstance(player, int) or isinstance(player, bool) for player in players):
            raise RuleError("Os jogadores precisam ter identificadores válidos.")
        if not isinstance(winner_count, int) or isinstance(winner_count, bool) or not 1 <= winner_count < len(players):
            raise RuleError("Escolha de 1 até o número de jogadores menos 1 vencedores.")
        if rules is not None and not isinstance(rules, Rules):
            raise RuleError("As regras da mesa são inválidas.")
        self.rules = rules or Rules()
        self.rng = rng or random.Random()
        self.players = players
        self.hands = {player: [] for player in players}
        self.winner_count = winner_count
        self.winners = []
        self.finished = False
        self.direction = 1
        self.pending_draw = 0
        self.challenge = None
        self.uno_pending = {}
        self.uno_called = set()
        self.drawn_player = None
        self.drawn_card_ids = set()
        self._empty_order = []
        self.revision = 0
        self.last_action = "A partida começou. Cada jogador recebeu 7 cartas."
        # Two packs accommodate a full 20-person table while preserving a draw pile.
        self.draw_pile = self._make_deck(max(1, math.ceil((7 * len(players) + 1) / 108)))
        self.rng.shuffle(self.draw_pile)
        # Choose the opening card before dealing, including crowded one-pack tables.
        opening_index = next(index for index, card in enumerate(self.draw_pile) if card.value in NUMBER_VALUES)
        self.discard_pile = [self.draw_pile.pop(opening_index)]
        for _ in range(7):
            for player in players:
                self.hands[player].append(self.draw_pile.pop())
        self.current_color = self.top.color
        self.current_player = players[0]
        self.turn_deadline = self._time(now) + TURN_SECONDS

    @staticmethod
    def _make_deck(packs):
        cards = []
        for pack in range(packs):
            for color in COLORS:
                # Sort numbers explicitly: seeded games must not depend on hash randomization.
                values = ["0"] + [str(value) for value in range(1, 10)] * 2 + ["skip", "reverse", "draw2"] * 2
                for index, value in enumerate(values):
                    cards.append(Card(f"{pack}:{color}:{index}", color, value))
            for value in ("wild", "wild4"):
                for index in range(4):
                    cards.append(Card(f"{pack}:{value}:{index}", None, value))
        return cards

    @staticmethod
    def _time(now):
        return time.monotonic() if now is None else float(now)

    @property
    def top(self):
        return self.discard_pile[-1]

    def _require_player(self, player_id):
        if self.finished:
            raise RuleError("Esta partida já terminou.")
        if player_id not in self.players:
            raise RuleError("Você não está jogando nesta mesa.")

    def _require_turn(self, player_id, now):
        self._require_player(player_id)
        if self.current_player != player_id:
            raise RuleError("Aguarde a sua vez.")
        if now >= self.turn_deadline:
            raise RuleError("O tempo desta jogada acabou. Aguarde a atualização da mesa.")

    def _next(self, player_id, steps=1):
        return self.players[(self.players.index(player_id) + self.direction * steps) % len(self.players)]

    def _has_color(self, player_id):
        return any(card.color == self.current_color for card in self.hands[player_id])

    def _playable(self, player_id, card):
        if self.drawn_player == player_id and card.uid not in self.drawn_card_ids:
            return False
        if self.pending_draw:
            return (self.rules.stack_draw and card.value in ("draw2", "wild4")
                    and (card.value != "wild4" or self.rules.challenge_draw4 or not self._has_color(player_id)))
        if card.value == "wild4":
            return self.rules.challenge_draw4 or not self._has_color(player_id)
        return card.value == "wild" or card.color == self.current_color or card.value == self.top.value

    def legal_cards(self, player_id):
        if self.finished or player_id != self.current_player or player_id not in self.players:
            return []
        return [card for card in self.hands[player_id] if self._playable(player_id, card)]

    def can_pass(self, player_id):
        return not self.finished and self.current_player == player_id and self.drawn_player == player_id

    def can_draw(self, player_id):
        return not self.finished and self.current_player == player_id and self.drawn_player is None

    def _take(self, player_id, amount):
        taken = []
        for _ in range(amount):
            if not self.draw_pile:
                if len(self.discard_pile) <= 1:
                    break
                self.draw_pile = self.discard_pile[:-1]
                self.discard_pile = self.discard_pile[-1:]
                self.rng.shuffle(self.draw_pile)
            card = self.draw_pile.pop()
            self.hands[player_id].append(card)
            taken.append(card)
        if taken:
            self.uno_called.discard(player_id)
            self.uno_pending.pop(player_id, None)
        return taken

    def _begin_action(self, now):
        # Keep the promised three seconds even if the next player acts quickly.
        # After those seconds, a forgotten call lasts until the next game action.
        self.uno_pending = {player: deadline for player, deadline in self.uno_pending.items() if now < deadline}

    def _set_turn(self, player_id, now):
        self.current_player = player_id
        self.turn_deadline = now + TURN_SECONDS
        self.drawn_player = None
        self.drawn_card_ids.clear()

    def _record_empty(self, preferred=()):
        self._empty_order = [player for player in self._empty_order if player in self.players and not self.hands[player]]
        for player in (*preferred, *self.players):
            if player in self.players and not self.hands[player] and player not in self._empty_order:
                self._empty_order.append(player)

    def _settle_winners(self):
        self._record_empty()
        for player in list(self._empty_order):
            if self.challenge is not None and player == self.challenge.offender:
                continue
            successor = self._next(player)
            self.players.remove(player)
            self._empty_order.remove(player)
            self.winners.append(player)
            self.uno_pending.pop(player, None)
            self.uno_called.discard(player)
            if self.current_player == player:
                self.current_player = successor
            if len(self.winners) >= self.winner_count or len(self.players) <= 1:
                if self.pending_draw:
                    taken = self._take(self.current_player, self.pending_draw)
                    self.last_action += f" <@{self.current_player}> comprou {len(taken)} cartas da penalidade final."
                    self.pending_draw = 0
                self.finished = True
                self.challenge = None
                self.uno_pending.clear()
                self.last_action += f" <@{player}> terminou em {len(self.winners)}º lugar. Partida encerrada."
                break
            self.last_action += f" <@{player}> terminou em {len(self.winners)}º lugar."

    def _refresh_uno(self, affected, now, declared_player=None):
        for player in affected:
            self.uno_called.discard(player)
            self.uno_pending.pop(player, None)
            if player in self.players and len(self.hands[player]) == 1:
                if player == declared_player:
                    self.uno_called.add(player)
                else:
                    self.uno_pending[player] = now + UNO_SECONDS

    def play(self, player_id, card_ids, color=None, target_id=None, declare_uno=False, now=None):
        now = self._time(now)
        self._require_turn(player_id, now)
        if isinstance(card_ids, str):
            card_ids = [card_ids]
        else:
            try:
                card_ids = list(card_ids)
            except TypeError as exc:
                raise RuleError("Escolha uma carta da sua mão.") from exc
        if not card_ids or any(not isinstance(uid, str) for uid in card_ids) or len(set(card_ids)) != len(card_ids):
            raise RuleError("Escolha cartas diferentes da sua mão.")
        hand = {card.uid: card for card in self.hands[player_id]}
        if any(uid not in hand for uid in card_ids):
            raise RuleError("Essa carta já saiu da sua mão. Abra sua mão novamente.")
        cards = [hand[uid] for uid in card_ids]
        if len(cards) > 1 and (not self.rules.multiple_cards or cards[0].value not in NUMBER_VALUES
                               or any(card.value != cards[0].value for card in cards)):
            raise RuleError("Só é permitido jogar juntas cartas numéricas iguais quando a regra está ativa.")
        first_playable = next((card for card in cards if self._playable(player_id, card)), None)
        if first_playable is None:
            raise RuleError("Essa carta não combina com a mesa ou não pode responder à compra pendente.")
        if len(cards) > 1:
            cards = [first_playable, *(card for card in cards if card != first_playable)]
        if self.drawn_player == player_id and any(card.uid not in self.drawn_card_ids for card in cards):
            raise RuleError("Depois de comprar, você só pode jogar a carta que acabou de comprar.")
        last = cards[-1]
        if last.value in ("wild", "wild4"):
            if color not in COLORS:
                raise RuleError("Escolha vermelho, amarelo, verde ou azul para o coringa.")
        elif color is not None and color != last.color:
            raise RuleError("Somente um coringa permite escolher uma cor diferente.")
        swapping = self.rules.seven_zero and last.value == "7"
        if swapping and (target_id not in self.players or target_id == player_id):
            raise RuleError("Escolha outro jogador da mesa para trocar as mãos.")
        illegal_four = last.value == "wild4" and self._has_color(player_id)
        previous_draw = self.pending_draw
        self._begin_action(now)
        self.challenge = None  # Playing accepts any previous +4 challenge.
        selected = set(card_ids)
        self.hands[player_id] = [card for card in self.hands[player_id] if card.uid not in selected]
        self.discard_pile.extend(cards)
        self.current_color = color if last.value in ("wild", "wild4") else last.color
        self.uno_called.discard(player_id)
        affected = [player_id]
        steps = 1
        if last.value == "reverse":
            self.direction *= -1
            if len(self.players) == 2:
                steps = 2
        elif last.value == "skip":
            steps = 2
        elif last.value == "draw2":
            self.pending_draw += 2
        elif last.value == "wild4":
            self.pending_draw += 4
        elif swapping:
            self.hands[player_id], self.hands[target_id] = self.hands[target_id], self.hands[player_id]
            affected = [player_id, target_id]
        elif self.rules.seven_zero and last.value == "0":
            previous_hands = {player: self.hands[player] for player in self.players}
            for player in self.players:
                self.hands[self._next(player)] = previous_hands[player]
            affected = list(self.players)
        next_player = self._next(player_id, steps)
        if last.value == "wild4" and self.rules.challenge_draw4:
            self.challenge = DrawFourChallenge(player_id, next_player, illegal_four, self.pending_draw, previous_draw)
        self._set_turn(next_player, now)
        transferring = self.rules.seven_zero and last.value in ("7", "0")
        self._refresh_uno(affected, now, player_id if declare_uno and not transferring else None)
        self.last_action = f"<@{player_id}> jogou {len(cards)} carta(s)."
        self._record_empty((player_id,))
        self._settle_winners()
        self.revision += 1

    def draw(self, player_id, now=None):
        now = self._time(now)
        self._require_turn(player_id, now)
        if self.drawn_player == player_id:
            raise RuleError("Você já comprou nesta vez. Jogue a carta comprada ou passe.")
        self._begin_action(now)
        self.challenge = None
        if self.pending_draw:
            owed = self.pending_draw
            taken = self._take(player_id, owed)
            self.pending_draw = 0
            self._set_turn(self._next(player_id), now)
            self.last_action = f"<@{player_id}> comprou {len(taken)} de {owed} cartas e passou a vez."
        else:
            taken = []
            while True:
                batch = self._take(player_id, 1)
                if not batch:
                    break
                taken.extend(batch)
                if self._playable(player_id, batch[0]) or not self.rules.draw_until_playable:
                    break
            playable = any(self._playable(player_id, card) for card in taken)
            self.last_action = f"<@{player_id}> comprou {len(taken)} carta(s)."
            if playable:
                self.drawn_player = player_id
                self.drawn_card_ids = {card.uid for card in taken}
                # Drawing does not give an additional 60 seconds for the same turn.
            else:
                self._set_turn(self._next(player_id), now)
                self.last_action += " A vez passou."
        self._settle_winners()
        self.revision += 1

    def pass_turn(self, player_id, now=None):
        now = self._time(now)
        self._require_turn(player_id, now)
        if not self.can_pass(player_id):
            raise RuleError("Compre uma carta antes de passar a vez.")
        self._begin_action(now)
        self._set_turn(self._next(player_id), now)
        self.last_action = f"<@{player_id}> passou a vez."
        self._settle_winners()
        self.revision += 1

    def challenge_draw_four(self, player_id, now=None):
        now = self._time(now)
        self._require_turn(player_id, now)
        challenge = self.challenge
        if challenge is None or challenge.challenger != player_id:
            raise RuleError("Não há um +4 para você desafiar.")
        self._begin_action(now)
        self.challenge = None
        if challenge.illegal:
            taken = self._take(challenge.offender, 4)
            self.pending_draw = challenge.previous_draw
            self._set_turn(player_id, now)
            self.last_action = f"Blefe! <@{challenge.offender}> tinha a cor da mesa e comprou {len(taken)} cartas. <@{player_id}> continua na vez."
        else:
            taken = self._take(player_id, challenge.amount + 2)
            self.pending_draw = 0
            self._set_turn(self._next(player_id), now)
            self.last_action = f"O +4 era válido. <@{player_id}> comprou {len(taken)} cartas e perdeu a vez."
        self._settle_winners()
        self.revision += 1

    def call_uno(self, player_id, now=None):
        now = self._time(now)
        self._require_player(player_id)
        if len(self.hands[player_id]) != 1:
            raise RuleError("Você só pode falar Six com uma carta na mão.")
        if player_id in self.uno_called:
            raise RuleError("Você já falou Six.")
        deadline = self.uno_pending.get(player_id)
        if deadline is None or now >= deadline:
            raise RuleError("Os 3 segundos para falar Six terminaram.")
        self.uno_called.add(player_id)
        self.uno_pending.pop(player_id, None)
        self.last_action = f"<@{player_id}> falou Six!"
        self.revision += 1

    def catch_uno(self, catcher_id, target_id=None, now=None):
        now = self._time(now)
        self._require_player(catcher_id)
        eligible = [player for player, deadline in self.uno_pending.items()
                    if player != catcher_id and player in self.players and len(self.hands[player]) == 1 and now >= deadline]
        if target_id is None:
            target_id = next(iter(eligible), None)
        if target_id not in eligible:
            raise RuleError("Ninguém pode ser pego agora. Aguarde os 3 segundos ou a próxima oportunidade.")
        taken = self._take(target_id, 2)
        self.uno_pending.pop(target_id, None)
        self.last_action = f"<@{catcher_id}> pegou <@{target_id}> sem falar Six: +{len(taken)} cartas."
        self.revision += 1

    def timeout(self, now=None):
        now = self._time(now)
        if self.finished or now < self.turn_deadline:
            return False
        player_id = self.current_player
        self._begin_action(now)
        self.challenge = None
        amount = self.pending_draw or 1
        taken = self._take(player_id, amount)
        self.pending_draw = 0
        self._set_turn(self._next(player_id), now)
        self.last_action = f"O tempo de <@{player_id}> acabou: comprou {len(taken)} carta(s) e perdeu a vez."
        self._settle_winners()
        self.revision += 1
        return True
