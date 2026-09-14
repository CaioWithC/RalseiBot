"""Pure game rules. Payouts always include the original stake."""
from fractions import Fraction
from math import comb
from random import SystemRandom

RNG = SystemRandom()
SLOT_SYMBOLS = ("🍒", "🍋", "🍇", "🔔", "⭐", "💎")
SLOT_TRIPLES = (3, 3, 3, 4, 5, 10)
SUITS = ("♠", "♥", "♦", "♣")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
MINE_CELLS = 16


def slot_multiplier(reels):
    if len(set(reels)) == 1:
        return SLOT_TRIPLES[SLOT_SYMBOLS.index(reels[0])]
    return 2 if len(set(reels)) == 2 else 0


def hand_value(hand):
    total = sum(11 if rank == "A" else 10 if rank in ("J", "Q", "K") else int(rank)
                for rank, suit in hand)
    aces = sum(rank == "A" for rank, suit in hand)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def format_hand(hand):
    return "  ".join(f"`{rank}{suit}`" for rank, suit in hand)


class Blackjack:
    def __init__(self, stake, deck=None):
        self.stake = stake
        self.deck = list(deck) if deck is not None else [(rank, suit) for suit in SUITS for rank in RANKS]
        if deck is None:
            RNG.shuffle(self.deck)
        self.player = [self.deck.pop()]
        self.dealer = [self.deck.pop()]
        self.player.append(self.deck.pop())
        self.dealer.append(self.deck.pop())
        self.payout = None
        self.result = "Peça uma carta ou pare. A banca para em qualquer 17."
        player_natural = hand_value(self.player) == 21
        dealer_natural = hand_value(self.dealer) == 21
        if player_natural or dealer_natural:
            if player_natural and dealer_natural:
                self.finish(stake, "Dois blackjacks: empate!")
            elif player_natural:
                self.finish(stake * 5 // 2, "Blackjack! Vitória com prêmio de 3:2.")
            else:
                self.finish(0, "A banca fez blackjack.")

    def finish(self, payout, result):
        self.payout, self.result = payout, result

    def hit(self):
        if self.payout is not None:
            return
        self.player.append(self.deck.pop())
        value = hand_value(self.player)
        if value > 21:
            self.finish(0, "Você estourou 21.")
        elif value == 21:
            self.stand()

    def stand(self):
        if self.payout is not None:
            return
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        player, dealer = hand_value(self.player), hand_value(self.dealer)
        if dealer > 21 or player > dealer:
            self.finish(self.stake * 2, "Você venceu!")
        elif player == dealer:
            self.finish(self.stake, "Empate: aposta devolvida.")
        else:
            self.finish(0, "A banca venceu.")


def mines_multiplier(mine_count, revealed):
    if revealed == 0:
        return Fraction(1)
    return Fraction(97, 100) * Fraction(comb(MINE_CELLS, revealed), comb(MINE_CELLS - mine_count, revealed))


class Mines:
    def __init__(self, stake, mine_count=3, mines=None):
        if type(mine_count) is not int or not 1 <= mine_count < MINE_CELLS:
            raise ValueError("Escolha entre 1 e 15 minas.")
        self.stake = stake
        self.mines = set(RNG.sample(range(MINE_CELLS), mine_count) if mines is None else mines)
        if len(self.mines) != mine_count or not self.mines <= set(range(MINE_CELLS)):
            raise ValueError("Tabuleiro inválido.")
        self.revealed = set()
        self.payout = None
        self.result = "Revele uma casa segura e retire quando quiser. Mina = perda da aposta."

    def multiplier(self, revealed=None):
        count = len(self.revealed) if revealed is None else revealed
        return mines_multiplier(len(self.mines), count)

    def cashout_value(self):
        return int(self.stake * self.multiplier())

    def reveal(self, cell):
        if self.payout is not None or cell in self.revealed:
            return
        if type(cell) is not int or not 0 <= cell < MINE_CELLS:
            raise ValueError("Casa inválida.")
        if cell in self.mines:
            self.payout, self.result = 0, "Você encontrou uma mina!"
        else:
            self.revealed.add(cell)
            if len(self.revealed) == MINE_CELLS - len(self.mines):
                self.cashout()
                self.result = "Todas as casas seguras reveladas! Retirada automática."

    def cashout(self):
        if self.payout is None and self.revealed:
            self.payout = self.cashout_value()
            self.result = "Você retirou seus DarkMoney!"
