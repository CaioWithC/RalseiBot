import asyncio
import logging
import uuid

import nextcord
from nextcord.ext import commands

from db import database, EconomyError
from cogs.amounts import BetAmount
from cogs.command_support import DualCommand
from cogs.game_rules import (Blackjack, Mines, Dice, DICE_SIDES, DICE_MULTIPLIERS,
                        RNG, SLOT_SYMBOLS, SLOT_TRIPLES,
                        format_hand, hand_value, slot_multiplier, mines_multiplier,
                        parse_dice, validate_guess)

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
            elif getattr(self.game, "revealed", None):
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
        super().__init__(custom_id=f"mines:bombs:{uuid.uuid4().hex}", placeholder="Escolha de 1 a 15 bombas para começar", options=options)

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


class DiceTypeButton(nextcord.ui.Button):
    def __init__(self, sides):
        multiplier = DICE_MULTIPLIERS[sides]
        super().__init__(label=f"d{sides} • {multiplier}×", emoji="🎲",
                         style=nextcord.ButtonStyle.primary, row=0)
        self.sides = sides

    async def callback(self, interaction):
        view = self.view
        if view is None or view.done:
            return
        await view.act(interaction, lambda: view.select_sides(self.sides))


class DiceNumberButton(nextcord.ui.Button):
    def __init__(self, number, sides):
        if sides == 6:
            row = (number - 1) // 3
        elif sides in (8, 12):
            row = (number - 1) // 4
        else:
            row = (number - 1) // 5
        super().__init__(label=str(number), style=nextcord.ButtonStyle.secondary, row=row)
        self.number = number
        self.sides = sides

    async def callback(self, interaction):
        view = self.view
        if view is None or view.done:
            return
        await view.act(interaction, lambda: view.pick_number(self.number))


class DiceBackButton(nextcord.ui.Button):
    def __init__(self, row):
        super().__init__(label="Trocar dado", emoji="🔙",
                         style=nextcord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction):
        view = self.view
        if view is None or view.done:
            return
        await view.act(interaction, view.back_to_dice_selection)


class DiceView(BettingView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.game.sides is None:
            self.show_dice_selection()
        else:
            self.show_number_selection(self.game.sides)

    def show_dice_selection(self):
        self.clear_items()
        for sides in DICE_SIDES:
            self.add_item(DiceTypeButton(sides))

    def show_number_selection(self, sides):
        self.clear_items()
        for number in range(1, sides + 1):
            self.add_item(DiceNumberButton(number, sides))
        if not self.done and self.game.payout is None:
            back_row = 2 if sides in (6, 8) else 3 if sides == 12 else 4
            self.add_item(DiceBackButton(back_row))

    def select_sides(self, sides):
        if self.done:
            return
        self.game.choose_sides(sides)
        self.show_number_selection(sides)

    def back_to_dice_selection(self):
        if self.done:
            return
        self.game.reset_sides()
        self.show_dice_selection()

    def pick_number(self, number):
        if self.done:
            return
        self.game.play(self.game.sides, number)

    def embed(self):
        game = self.game
        if game.sides is None:
            embed = nextcord.Embed(
                title="🎲 Aposta no Dado • Escolha o dado",
                color=GREEN,
                description=(
                    "Escolha quantos lados o dado terá para a sua aposta.\n"
                    "**Quanto mais lados, maior o multiplicador e o prêmio!**\n\n"
                    + "\n".join(
                        f"• **d{s}**: multiplicador **{DICE_MULTIPLIERS[s]}×** (chances: 1 em {s})"
                        for s in DICE_SIDES
                    )
                ),
            )
            if not self.done:
                embed.set_footer(text="Aposta reservada • 120s sem jogar: reembolso • Retornos incluem a aposta")
            return self.add_summary(embed)

        if not self.done and game.payout is None:
            embed = nextcord.Embed(
                title=f"🎲 Aposta no Dado • d{game.sides}",
                color=GREEN,
                description=(
                    f"Você escolheu o **d{game.sides}** (multiplicador **{DICE_MULTIPLIERS[game.sides]}×**).\n"
                    f"Escolha em qual número você aposta que o dado vai cair (1 a {game.sides}):"
                ),
            )
            embed.set_footer(text="Aposta reservada • 120s sem jogar: reembolso • Retornos incluem a aposta")
            return self.add_summary(embed)

        if self.done and game.sides is not None:
            for item in self.children:
                if isinstance(item, DiceNumberButton):
                    if item.number == game.roll and item.number == game.guess:
                        item.style = nextcord.ButtonStyle.success
                        item.emoji = "🎉"
                    elif item.number == game.roll:
                        item.style = nextcord.ButtonStyle.primary
                        item.emoji = "🎲"
                    elif item.number == game.guess:
                        item.style = nextcord.ButtonStyle.danger
                        item.emoji = "❌"
                    item.disabled = True
                elif isinstance(item, DiceBackButton):
                    item.disabled = True

        embed = nextcord.Embed(
            title=f"🎲 Aposta no Dado • d{game.sides}",
            color=GREEN,
            description=game.result,
        )
        embed.add_field(name="Dado", value=f"d{game.sides} ({DICE_MULTIPLIERS[game.sides]}×)", inline=True)
        embed.add_field(name="Seu palpite", value=str(game.guess), inline=True)
        embed.add_field(name="Resultado do dado", value=f"🎲 {game.roll}", inline=True)
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

    @commands.command(cls=DualCommand, aliases=["dado", "dados"], help="Aposte no dado: r.dice <aposta> [dado] [número]. Escolha d6 (6×), d8 (8×), d12 (12×) ou d20 (20×). Omita o dado ou o número para jogar com botões.")
    @commands.cooldown(1, 3, lambda message: message.author.id)
    async def dice(self, ctx, amount: BetAmount, dice: str = None, number: int = None):
        sides = parse_dice(dice)
        if number is not None and sides is None:
            raise EconomyError("Escolha o dado (d6, d8, d12 ou d20) para o qual você deseja apostar o número.")
        guess = validate_guess(number, sides) if number is not None else None
        await self.start_game(
            ctx, amount, "dice",
            lambda stake: Dice(stake, sides=sides, guess=guess),
            DiceView,
        )


def setup(bot):
    bot.add_cog(Games(bot))

