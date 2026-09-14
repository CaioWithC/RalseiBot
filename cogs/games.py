import asyncio
import logging

import nextcord
from nextcord.ext import commands

from db import database, EconomyError
from cogs.amounts import BetAmount
from cogs.command_support import DualCommand
from cogs.game_rules import (Blackjack, Mines, RNG, SLOT_SYMBOLS, SLOT_TRIPLES,
                        format_hand, hand_value, slot_multiplier, mines_multiplier)

log = logging.getLogger(__name__)
GREEN = 0x77E5BC


class BettingView(nextcord.ui.View):
    def __init__(self, owner_id, bet_id, game, storage=None):
        super().__init__(timeout=120)
        self.owner_id, self.bet_id, self.game = owner_id, bet_id, game
        self.storage = storage if storage is not None else database
        self.lock = asyncio.Lock()
        self.message = None
        self.done = False
        self.final_balance = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Este jogo pertence a outro jogador. Inicie o seu com `r.help`.", ephemeral=True)
            return False
        return True

    def settle(self, refund=False):
        if self.done:
            return
        self.final_balance = self.storage.settle_bet(self.bet_id, None if refund else self.game.payout)
        self.done = True
        for item in self.children:
            item.disabled = True
        self.stop()

    async def act(self, interaction, action):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                await interaction.followup.send("Este jogo já terminou.", ephemeral=True)
                return
            action()
            if self.game.payout is not None:
                self.settle()
            await interaction.message.edit(embed=self.embed(), view=self)

    async def on_timeout(self):
        async with self.lock:
            if self.done:
                return
            if isinstance(self.game, Blackjack):
                self.game.stand()
                self.game.result = "Tempo esgotado: parar automático. " + self.game.result
                self.settle()
            elif self.game.revealed:
                self.game.cashout()
                self.game.result = "Tempo esgotado: retirada automática."
                self.settle()
            else:
                self.game.payout = self.game.stake
                self.game.result = "Tempo esgotado sem jogadas: aposta devolvida."
                self.settle(refund=True)
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except nextcord.HTTPException:
                    log.warning("Could not update expired game %s", self.bet_id)

    async def on_error(self, error, item, interaction):
        log.error("Game interaction failed", exc_info=(type(error), error, error.__traceback__))
        async with self.lock:
            if not self.done:
                self.game.payout = self.game.stake
                self.game.result = "Jogo interrompido por erro: aposta devolvida."
                self.settle(refund=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("O jogo foi encerrado. Confira o saldo com `r.balance`.", ephemeral=True)
            else:
                await interaction.response.send_message("O jogo foi encerrado. Confira o saldo com `r.balance`.", ephemeral=True)
            if self.message:
                await self.message.edit(embed=self.embed(), view=self)
        except nextcord.HTTPException:
            log.warning("Could not report failed game %s", self.bet_id)

    def add_summary(self, embed):
        embed.description = f"<@{self.owner_id}>\n{embed.description}"
        embed.add_field(name="Aposta", value=f"{self.game.stake:,} DarkMoney", inline=True)
        if self.done:
            payout = self.game.payout
            embed.add_field(name="Retorno total", value=f"{payout:,} DarkMoney", inline=True)
            embed.add_field(name="Resultado líquido", value=f"{payout - self.game.stake:+,}", inline=True)
            embed.set_footer(text=f"Saldo: {self.final_balance:,} DarkMoney • Retorno inclui a aposta")
        return embed


class BlackjackView(BettingView):
    @nextcord.ui.button(label="Pedir carta", emoji="🃏", style=nextcord.ButtonStyle.primary)
    async def hit(self, button, interaction):
        await self.act(interaction, self.game.hit)

    @nextcord.ui.button(label="Parar", emoji="✋", style=nextcord.ButtonStyle.success)
    async def stand(self, button, interaction):
        await self.act(interaction, self.game.stand)

    def embed(self):
        game = self.game
        embed = nextcord.Embed(title="♠ Blackjack", description=game.result, color=GREEN)
        embed.add_field(name=f"Sua mão • {hand_value(game.player)}", value=format_hand(game.player), inline=False)
        if self.done:
            embed.add_field(name=f"Banca • {hand_value(game.dealer)}", value=format_hand(game.dealer), inline=False)
        else:
            embed.add_field(name="Banca", value=format_hand(game.dealer[:1]) + "  `?`", inline=False)
            embed.set_footer(text="120s sem ação: parar automático • Vitória 2× / natural 2,5× / empate 1×")
        return self.add_summary(embed)


class MineButton(nextcord.ui.Button):
    def __init__(self, cell):
        super().__init__(label=str(cell + 1), style=nextcord.ButtonStyle.secondary, row=cell // 4)
        self.cell = cell

    async def callback(self, interaction):
        await self.view.act(interaction, lambda: self.view.game.reveal(self.cell))


class MineCountSelect(nextcord.ui.Select):
    def __init__(self, stake):
        options = []
        for count in range(1, 16):
            multiplier = mines_multiplier(count, 1)
            options.append(nextcord.SelectOption(
                label=f"{count} bomba(s) • {float(multiplier):.2f}×",
                value=str(count), emoji="💣",
                description=f"1ª casa segura: {int(stake * multiplier):,} DarkMoney • {16 - count}/16 casas seguras"))
        super().__init__(placeholder="Escolha de 1 a 15 bombas para começar", options=options)

    async def callback(self, interaction):
        count = int(self.values[0])
        view = self.view
        if view is None:
            await interaction.response.send_message("A quantidade de bombas já foi escolhida.", ephemeral=True)
            return
        await view.act(interaction, lambda: view.choose_bombs(count))


class MinesView(BettingView):
    def __init__(self, *args, choose_mines=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.choosing = choose_mines
        if self.choosing:
            self.clear_items()
            self.add_item(MineCountSelect(self.game.stake))
        else:
            self.add_board()

    def add_board(self):
        self.clear_items()
        self.add_item(self.cashout)
        for cell in range(16):
            self.add_item(MineButton(cell))

    def choose_bombs(self, count):
        # A queued second selection must not replace an already started board.
        if not self.choosing or self.done:
            return
        self.game = Mines(self.game.stake, count)
        self.choosing = False
        self.add_board()

    @nextcord.ui.button(label="Retirar", emoji="💰", style=nextcord.ButtonStyle.success, row=4, disabled=True)
    async def cashout(self, button, interaction):
        await self.act(interaction, self.game.cashout)

    def embed(self):
        game = self.game
        if self.choosing:
            embed = nextcord.Embed(title="💣 Mines • Escolha as bombas", color=GREEN,
                                  description=game.result if self.done else
                                  "Escolha quantas bombas quer no tabuleiro 4×4.\n"
                                  "**Mais bombas = maior multiplicador e maior risco.**\n"
                                  "O menu mostra o retorno após a primeira casa segura.")
            if not self.done:
                embed.set_footer(text="Aposta reservada • 120s sem escolher: reembolso • Retornos incluem a aposta")
            return self.add_summary(embed)
        for item in self.children:
            if isinstance(item, MineButton):
                if item.cell in game.revealed:
                    item.label, item.emoji = " ", "💎"
                    item.style, item.disabled = nextcord.ButtonStyle.success, True
                elif self.done and item.cell in game.mines:
                    item.label, item.emoji = " ", "💣"
                    item.style = nextcord.ButtonStyle.danger
            else:
                item.disabled = self.done or not game.revealed
        embed = nextcord.Embed(title="💎 Mines • 4 × 4", description=game.result, color=GREEN)
        embed.add_field(name="Minas", value=str(len(game.mines)))
        embed.add_field(name="Casas seguras abertas", value=f"{len(game.revealed)}/{16 - len(game.mines)}")
        if not self.done:
            embed.add_field(name="Retirada atual", value=f"{game.cashout_value():,} DarkMoney ({float(game.multiplier()):.2f}×)", inline=False)
            next_multiplier = game.multiplier(len(game.revealed) + 1)
            embed.add_field(name="Próxima casa segura", value=f"{int(game.stake * next_multiplier):,} DarkMoney ({float(next_multiplier):.2f}×)", inline=False)
            embed.set_footer(text="120s sem ação: retirada automática; sem jogadas: reembolso • Retornos arredondados para baixo")
        return self.add_summary(embed)


class Games(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database

    @commands.command(cls=DualCommand, aliases=["slot", "slotmachine"], help="Gire 3 rolos: r.slots <aposta>. Aceita 10k, 1m, half e all; sem teto fixo, limitado ao saldo. Par 2×; trincas 3× a 10×.")
    # Use a callable key to avoid Nextcord 3.2's BucketType mapping error.
    @commands.cooldown(1, 3, lambda message: message.author.id)
    async def slots(self, ctx, amount: BetAmount):
        bet_id = self.storage.reserve_bet(ctx.author.id, "slots", amount)
        try:
            amount = self.storage.bet_stake(bet_id)
            reels = [RNG.choice(SLOT_SYMBOLS) for _ in range(3)]
            multiplier = slot_multiplier(reels)
            payout = amount * multiplier
            balance = self.storage.settle_bet(bet_id, payout)
            embed = nextcord.Embed(title="🎰 Caça-níqueis", color=GREEN,
                                  description=f"<@{ctx.author.id}>\n\n" + "  │  ".join(reels) + f"\n\n**{'Você ganhou!' if payout else 'Não foi dessa vez.'}**")
            embed.add_field(name="Aposta", value=f"{amount:,} DarkMoney")
            embed.add_field(name=f"Retorno total • {multiplier}×", value=f"{payout:,} DarkMoney")
            embed.add_field(name="Resultado líquido", value=f"{payout - amount:+,}")
            triples = " • ".join(f"{symbol} {value}×" for symbol, value in zip(SLOT_SYMBOLS, SLOT_TRIPLES))
            embed.add_field(name="Tabela de retornos", value=f"Trincas: {triples}\nQualquer par: 2× • Todos diferentes: 0×", inline=False)
            embed.set_footer(text=f"Saldo: {balance:,} DarkMoney • Retornos incluem a aposta")
            await ctx.send(embed=embed)
        except Exception:
            self.storage.settle_bet(bet_id)  # Only an unsettled bet can be refunded.
            raise

    async def start_game(self, ctx, amount, name, factory, view_type, **view_options):
        bet_id = self.storage.reserve_bet(ctx.author.id, name, amount)
        view = None
        try:
            amount = self.storage.bet_stake(bet_id)
            game = factory(amount)
            view = view_type(ctx.author.id, bet_id, game, storage=self.storage, **view_options)
            if game.payout is not None:
                view.settle()
            view.message = await ctx.send(embed=view.embed(), view=view)
        except Exception:
            if view:
                view.stop()
            self.storage.settle_bet(bet_id)
            raise

    @commands.command(cls=DualCommand, aliases=["bj", "21"], help="Blackjack com botões: r.blackjack <aposta>. Aceita 10k, 1m, half e all; limitado ao saldo. Banca para no 17; natural paga 3:2. Sem divisão/dobro.")
    async def blackjack(self, ctx, amount: BetAmount):
        await self.start_game(ctx, amount, "blackjack", Blackjack, BlackjackView)

    @commands.command(cls=DualCommand, aliases=["minas"], help="r.mines <aposta> [bombas]. Aceita 10k, 1m, half e all; limitado ao saldo. Escolha 1–15 bombas no menu ou no comando. Mais bombas = maior multiplicador e risco. Tabuleiro 4×4; margem: 3%.")
    async def mines(self, ctx, amount: BetAmount, mine_count: int = None):
        if mine_count is not None and not 1 <= mine_count <= 15:
            raise EconomyError("Escolha entre 1 e 15 minas.")
        await self.start_game(ctx, amount, "mines", lambda stake: Mines(stake, mine_count if mine_count is not None else 3),
                              MinesView, choose_mines=mine_count is None)


def setup(bot):
    bot.add_cog(Games(bot))
