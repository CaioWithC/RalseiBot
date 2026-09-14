"""Discord poker lobby, private hands, betting controls and table lifecycle."""
import asyncio
from dataclasses import dataclass, field
import logging
import random
import time
import uuid

import nextcord
from nextcord.ext import commands, tasks

from cogs.amounts import CoinAmount, parse_amount
from cogs.command_support import DualCommand
from cogs.poker_render import render_hand, render_table
from cogs.poker_rules import HAND_NAMES, STREETS, Holdem, Player, PokerError, best_hand, bot_decision
from db import EconomyError, database

log = logging.getLogger(__name__)
GREEN = 0x77E5BC
LOBBY_SECONDS, TURN_SECONDS, BOT_SECONDS = 300, 60, 2
BOT_NAMES = ("Kris", "Susie", "Lancer", "Noelle")


async def private_reply(interaction, content, **kwargs):
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(content, ephemeral=True, **kwargs)


@dataclass
class Table:
    id: str
    host_id: int
    channel_id: int
    guild_id: int
    stake: int
    members: dict
    deadline: float
    dealer_avatar: bytes = None
    game: Holdem = None
    status: str = "lobby"
    message: object = None
    view: object = None
    receipt: dict = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PokerView(nextcord.ui.View):
    def __init__(self, cog, table):
        super().__init__(timeout=None)
        self.cog, self.table = cog, table
        self.revision = table.game.revision if table.game else None
        if table.status == "lobby":
            for label, action, style in (("Entrar", "join", nextcord.ButtonStyle.success),
                                         ("Sair", "leave", nextcord.ButtonStyle.secondary),
                                         ("Começar", "start", nextcord.ButtonStyle.primary),
                                         ("Cancelar", "cancel", nextcord.ButtonStyle.danger)):
                self.add_button(label, action, style)
        elif table.status == "playing":
            game, player = table.game, table.game.actor
            self.add_button("Ver minhas cartas", "hand", nextcord.ButtonStyle.secondary)
            call = min(player.stack, game.to_call(player))
            call_label = f"Pagar {call:,} D$" if call else "Mesa (check)"
            self.add_button(call_label, "call" if call else "check", nextcord.ButtonStyle.success,
                            disabled=player.bot)
            self.add_button("Aumentar", "raise", nextcord.ButtonStyle.primary,
                            disabled=player.bot or not game.can_raise(player)
                            or player.stack + player.street_bet < game.min_raise_to)
            self.add_button("All-in", "allin", nextcord.ButtonStyle.primary,
                            disabled=player.bot or (player.stack > game.to_call(player)
                                                   and not game.can_raise(player)))
            self.add_button("Desistir (fold)", "fold", nextcord.ButtonStyle.danger, disabled=player.bot)

    def add_button(self, label, action, style, *, disabled=False):
        button = nextcord.ui.Button(label=label[:80], style=style, disabled=disabled)

        async def callback(interaction):
            if action == "hand":
                await self.cog.show_hand(self.table, interaction)
            elif self.revision is None:
                await interaction.response.defer(ephemeral=True)
                await self.cog.lobby_action(self.table, interaction.user, action)
            elif action == "raise":
                async with self.table.lock:
                    self.cog.check_turn(self.table, interaction.user.id, self.revision)
                    await interaction.response.send_modal(RaiseModal(self.cog, self.table, self.revision,
                                                                      interaction.user.id))
            else:
                await interaction.response.defer(ephemeral=True)
                await self.cog.play(self.table, interaction.user.id, self.revision, action)

        button.callback = callback
        self.add_item(button)

    async def on_error(self, error, item, interaction):
        await self.cog.report_error(self.table, interaction, error)


class RaiseModal(nextcord.ui.Modal):
    def __init__(self, cog, table, revision, owner_id):
        super().__init__(title="Aumentar aposta", timeout=TURN_SECONDS)
        self.cog, self.table, self.revision, self.owner_id = cog, table, revision, owner_id
        self.amount = nextcord.ui.TextInput(label="Total em D$ nesta rodada (inclui o já pago)",
                                          default_value=str(table.game.min_raise_to),
                                          placeholder="Ex.: 100, 1k ou 1.5k", max_length=24)
        self.add_item(self.amount)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            if interaction.user.id != self.owner_id:
                raise PokerError("Este aumento pertence a outro jogador.")
            amount = parse_amount(self.amount.value, allow_aliases=False)
            await self.cog.play(self.table, interaction.user.id, self.revision, "raise", amount)
        except (PokerError, EconomyError, commands.BadArgument) as error:
            await private_reply(interaction, str(error))

    async def on_error(self, error, interaction):
        await self.cog.report_error(self.table, interaction, error)


class Poker(commands.Cog):
    def __init__(self, bot, storage=None, clock=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.clock = clock or time.monotonic
        self.tables, self.memberships = {}, {}
        self.registry_lock = asyncio.Lock()
        self.recovered = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.recovered:
            self.storage.recover_poker_games()
            self.recovered = True
        if not self.tick.is_running():
            self.tick.start()

    def cog_unload(self):
        self.tick.cancel()
        for table in list(self.tables.values()):
            if table.status == "playing":
                self.storage.cancel_poker_game(table.id)
            table.status = "cancelled"
            self.release(table)

    def release(self, table):
        self.tables.pop(table.id, None)
        for pid in table.members:
            if self.memberships.get(pid) == table.id:
                self.memberships.pop(pid, None)
        if table.view:
            table.view.stop()

    @commands.command(cls=DualCommand, aliases=["holdem"], help=(
        "Texas Hold’em com Ralsei como dealer: r.poker 1000 ou /poker amount:1000. "
        "Entrada mínima de 20 D$ (aceita K/M). Lobby para 1–6 pessoas; solo joga com 4 bots. "
        "Uma mão completa, cartas privadas e 60 segundos por vez. Fichas finais voltam ao saldo."))
    @commands.guild_only()
    async def poker(self, ctx, amount: CoinAmount = 1000):
        self.storage.positive(amount)
        if amount < 20:
            raise EconomyError("A entrada mínima é de 20 D$.")
        if self.storage.balance(ctx.author.id) < amount:
            raise EconomyError("Você não tem saldo suficiente para essa entrada.")
        table = Table(uuid.uuid4().hex, ctx.author.id, ctx.channel.id, ctx.guild.id,
                      amount, {ctx.author.id: ctx.author.display_name}, self.clock() + LOBBY_SECONDS)
        async with self.registry_lock:
            if ctx.author.id in self.memberships:
                raise EconomyError("Você já está em uma mesa de poker. Saia dela ou termine a mão.")
            self.tables[table.id] = table
            self.memberships[ctx.author.id] = table.id
        try:
            if self.bot.user:
                table.dealer_avatar = await self.bot.user.display_avatar.with_size(256).with_static_format("png").read()
            image = await self.table_picture(table)
            table.view = PokerView(self, table)
            table.message = await ctx.send(embed=self.embed(table), view=table.view,
                                           file=nextcord.File(image, "poker-table.png"))
        except BaseException:
            self.release(table)
            raise

    def embed(self, table):
        embed = nextcord.Embed(title="♠ Poker · Texas Hold’em", color=GREEN)
        if table.status == "lobby":
            small = max(1, table.stake // 100)
            embed.description = (f"**Ralsei é o dealer.** Anfitrião: <@{table.host_id}>\n"
                f"Entrada: **{table.stake:,} D$** por pessoa · blinds: **{small:,}/{small * 2:,} D$**.\n"
                "Clique em **Entrar** para aceitar a entrada. O anfitrião clica em **Começar**.\n"
                "**1 pessoa:** joga com Kris, Susie, Lancer e Noelle (bots).\n"
                "**2–6 pessoas:** jogam entre si. O lobby expira em 5 minutos.\n"
                "A entrada só é debitada ao começar. Cada partida dura **uma mão**; "
                "as fichas restantes e os ganhos voltam ao saldo no final.")
            embed.add_field(name=f"Jogadores ({len(table.members)}/6)",
                            value="\n".join(f"<@{pid}>" for pid in table.members), inline=False)
        elif table.status == "cancelled":
            embed.description = "Mesa encerrada. As entradas debitadas foram devolvidas."
        else:
            game = table.game
            embed.description = f"**Ralsei · Dealer** | {STREETS[game.street]} | Pote: **{game.pot:,} D$**"
            if not game.done:
                player = game.actor
                turn = player.name + " (bot)" if player.bot else f"<@{player.id}>"
                embed.description += (f"\nVez de **{turn}** · para pagar: **{min(player.stack, game.to_call(player)):,} D$**.\n"
                    "Use **Ver minhas cartas** para ver sua mão em privado. "
                    "Sem ação por 60s: passa se puder, senão desiste.")
            else:
                names = {p.id: p.name for p in game.players}
                pots = "\n".join(f"{'Pote principal' if index == 0 else 'Pote lateral ' + str(index)}: "
                                 f"{amount:,} D$ → " + ", ".join(names[pid] for pid in winners)
                                 for index, (amount, winners) in enumerate(game.pots))
                embed.add_field(name="Resultado", value=pots[:1024] or "Mão encerrada.", inline=False)
                balances = "\n".join(f"<@{p.id}>: **{p.stack:,} D$** devolvidos "
                                     f"({p.stack - table.stake:+,} D$)"
                                     for p in game.players if not p.bot)
                embed.add_field(name="Fichas creditadas no saldo", value=balances, inline=False)
                if game.showdown:
                    hands = "\n".join(f"{p.name}: {' '.join(map(str, p.cards))} · "
                                       f"{HAND_NAMES[best_hand(p.cards + game.board)[0]]}"
                                       for p in game.players if not p.folded)
                    embed.add_field(name="Showdown", value=hands[:1024], inline=False)
                embed.set_footer(text="Abra outra mesa com /poker ou r.poker. Ralsei agradece a partida!")
            if game.log:
                embed.add_field(name="Últimas jogadas", value="\n".join(game.log[-4:])[:1024], inline=False)
        embed.set_image(url="attachment://poker-table.png")
        return embed

    async def table_picture(self, table):
        players = table.game.players if table.game else [Player(pid, name, table.stake)
                                                         for pid, name in table.members.items()]
        return await asyncio.to_thread(render_table, players, game=table.game, stake=table.stake,
                                       dealer_avatar=table.dealer_avatar, cancelled=table.status == "cancelled")

    async def publish(self, table):
        image = await self.table_picture(table)
        view = PokerView(self, table) if table.status in ("lobby", "playing") else None
        try:
            await table.message.edit(embed=self.embed(table), view=view, attachments=[],
                                     file=nextcord.File(image, "poker-table.png"))
        except BaseException:
            if view:
                view.stop()
            raise
        if table.view:
            table.view.stop()
        table.view = view

    async def lobby_action(self, table, user, action):
        async with table.lock:
            if table.status != "lobby":
                raise PokerError("Este lobby já foi encerrado.")
            if action == "join":
                async with self.registry_lock:
                    if user.bot:
                        raise PokerError("Os bots da mesa são adicionados automaticamente no modo solo.")
                    if user.id in self.memberships:
                        raise PokerError("Você já está em uma mesa de poker.")
                    if len(table.members) >= 6:
                        raise PokerError("A mesa está cheia (6 pessoas).")
                    if self.storage.balance(user.id) < table.stake:
                        raise EconomyError("Você não tem saldo suficiente para essa entrada.")
                    table.members[user.id] = user.display_name
                    self.memberships[user.id] = table.id
            elif action == "leave":
                if user.id not in table.members:
                    raise PokerError("Você não está nesta mesa.")
                table.members.pop(user.id)
                self.memberships.pop(user.id, None)
                if not table.members:
                    await self.cancel(table)
                    return
                if table.host_id == user.id:
                    table.host_id = next(iter(table.members))
            elif action in ("start", "cancel"):
                if user.id != table.host_id:
                    raise PokerError("Só o anfitrião pode começar ou cancelar a mesa.")
                if action == "cancel":
                    await self.cancel(table)
                    return
                players = [Player(pid, name, table.stake) for pid, name in table.members.items()]
                bots = 4 if len(players) == 1 else 0
                players.extend(Player(-index, name, table.stake, bot=True)
                               for index, name in enumerate(BOT_NAMES, 1) if bots)
                game = Holdem(players, button=random.SystemRandom().randrange(len(players)),
                              small_blind=max(1, table.stake // 100))
                table.receipt = self.storage.start_poker_game(table.id, list(table.members), table.stake, bots=bots)
                table.game, table.status = game, "playing"
            else:
                raise PokerError("Ação desconhecida.")
            try:
                await self.publish(table)
                if table.status == "playing":
                    self.set_deadline(table)
            except Exception:
                await self.cancel(table, publish=False)
                raise

    def set_deadline(self, table):
        table.deadline = self.clock() + (BOT_SECONDS if table.game.actor.bot else TURN_SECONDS)

    def check_turn(self, table, player_id, revision):
        if table.status != "playing" or table.game.done:
            raise PokerError("Esta mão já foi encerrada.")
        if table.game.revision != revision:
            raise PokerError("A mesa mudou. Use os botões da mensagem atual.")
        if table.game.actor.id != player_id:
            raise PokerError("Aguarde a sua vez.")
        if self.clock() >= table.deadline:
            raise PokerError("O prazo desta jogada acabou. Aguarde a atualização da mesa.")

    async def play(self, table, player_id, revision, action, amount=None):
        async with table.lock:
            self.check_turn(table, player_id, revision)
            table.game.act(player_id, action, amount)
            try:
                await self.after_action(table)
            except Exception:
                await self.cancel(table)
                raise

    async def after_action(self, table):
        if table.game.done:
            table.receipt = self.storage.finish_poker_game(table.id, {p.id: p.stack for p in table.game.players})
            table.status = "finished"
            self.release(table)
        await self.publish(table)
        if table.status == "playing":
            self.set_deadline(table)

    async def show_hand(self, table, interaction):
        await interaction.response.defer(ephemeral=True)
        async with table.lock:
            if table.status != "playing" or interaction.user.id not in table.members:
                raise PokerError("Você precisa estar jogando nesta mesa para ver suas cartas.")
            player = next(p for p in table.game.players if p.id == interaction.user.id)
            picture = await asyncio.to_thread(render_hand, player)
            await private_reply(interaction, "Suas cartas: " + " · ".join(map(str, player.cards)),
                                file=nextcord.File(picture, "poker-hand.png"))

    async def cancel(self, table, *, publish=True):
        # Call with table.lock held. Never overwrite a successfully committed result.
        if table.status in ("finished", "cancelled"):
            return
        if table.status == "playing":
            table.receipt = self.storage.cancel_poker_game(table.id)
        table.status = "cancelled"
        self.release(table)
        if publish and table.message:
            try:
                await table.message.edit(content="Mesa de poker encerrada. Entradas debitadas foram devolvidas.",
                                         embed=None, attachments=[], view=None)
            except nextcord.HTTPException:
                log.warning("Could not update cancelled poker table %s", table.id)

    async def report_error(self, table, interaction, error):
        if isinstance(error, (PokerError, EconomyError, commands.BadArgument)):
            await private_reply(interaction, str(error))
            return
        log.error("Poker interaction failed", exc_info=(type(error), error, error.__traceback__))
        async with table.lock:
            await self.cancel(table)
        text = ("A mão terminou e as fichas já foram creditadas. Consulte seu saldo." if table.status == "finished"
                else "A mesa foi interrompida. As entradas debitadas foram devolvidas.")
        try:
            await private_reply(interaction, text)
        except nextcord.HTTPException:
            log.warning("Could not report poker outcome")

    async def tick_table(self, table):
        async with table.lock:
            if table.status not in ("lobby", "playing") or self.clock() < table.deadline:
                return
            if table.status == "lobby":
                await self.cancel(table)
                return
            game, player = table.game, table.game.actor
            if player.bot:
                action, amount = await asyncio.to_thread(bot_decision, tuple(player.cards), tuple(game.board),
                    opponents=sum(not p.folded and p.id != player.id for p in game.players),
                    stack=player.stack, street_bet=player.street_bet, to_call=game.to_call(player), pot=game.pot,
                    minimum=game.min_raise_to, can_raise=game.can_raise(player))
            else:
                action, amount = ("check" if not game.to_call(player) else "fold"), None
            game.act(player.id, action, amount)
            await self.after_action(table)

    @tasks.loop(seconds=1)
    async def tick(self):
        for table in list(self.tables.values()):
            try:
                await self.tick_table(table)
            except Exception:
                log.exception("Poker table tick failed: %s", table.id)
                async with table.lock:
                    await self.cancel(table)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        for table in list(self.tables.values()):
            if table.message and table.message.id == payload.message_id:
                async with table.lock:
                    await self.cancel(table, publish=False)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        for table in list(self.tables.values()):
            if table.message and table.message.id in payload.message_ids:
                async with table.lock:
                    await self.cancel(table, publish=False)

    async def close_channel(self, channel_id):
        for table in list(self.tables.values()):
            if table.channel_id == channel_id:
                async with table.lock:
                    await self.cancel(table, publish=False)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.close_channel(channel.id)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        await self.close_channel(thread.id)


def setup(bot):
    bot.add_cog(Poker(bot))
