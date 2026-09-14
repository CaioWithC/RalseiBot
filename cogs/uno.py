"""Public Six/Uno tables and private, revision-checked hands for Discord."""
import asyncio
from dataclasses import dataclass, field, replace
import logging
import math
import time
import uuid

import nextcord
from nextcord.ext import commands, tasks

from cogs.command_support import DualCommand
from cogs.uno_rules import UnoGame, Rules, RuleError, COLORS, UNO_SECONDS
from cogs.uno_render import DECKS, card_label, render_card, render_hand
from db import EconomyError, database

log = logging.getLogger(__name__)
GREEN = 0x77E5BC
LOBBY_SECONDS = 900
RULE_OPTIONS = (
    ("challenge_draw4", "Desafiar +4", "Chame o blefe: quem tinha a cor compra 4; desafio errado compra 6."),
    ("stack_draw", "Empilhar +2/+4", "Responda qualquer +2/+4 com outro +2/+4 e passe a soma."),
    ("multiple_cards", "Jogar cartas repetidas", "Jogue várias cartas do mesmo número de uma vez."),
    ("draw_until_playable", "Comprar até jogar", "Sem carta jogável? Compre até encontrar uma."),
    ("seven_zero", "7–0 (troca de mãos)", "7 troca sua mão com alguém; 0 gira as mãos na direção da rodada."),
)
COLOR_NAMES = {"red": "🔴 Vermelho", "yellow": "🟡 Amarelo", "green": "🟢 Verde", "blue": "🔵 Azul"}


async def private_reply(interaction, content=None, **kwargs):
    if interaction.response.is_done():
        return await interaction.followup.send(content, ephemeral=True, **kwargs)
    return await interaction.response.send_message(content, ephemeral=True, **kwargs)


def staff(member):
    permissions = member.guild_permissions
    return permissions.administrator or permissions.manage_threads or permissions.manage_messages


@dataclass
class Table:
    id: str
    guild_id: int
    channel_id: int
    host_id: int
    members: dict
    rules: Rules = field(default_factory=Rules)
    winners: int = 1
    stake: int = 0
    deck: str = "normal"
    ready: set = field(default_factory=set)
    status: str = "lobby"
    created_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    thread: object = None
    invite: object = None
    message: object = None
    view: object = None
    invite_view: object = None
    game: object = None
    receipt: object = None
    uno_display: tuple = ()
    retry_at: float = 0


class SafeView(nextcord.ui.View):
    def __init__(self, cog, table=None, *, owner_id=None, timeout=600):
        super().__init__(timeout=timeout)
        self.cog, self.table, self.owner_id = cog, table, owner_id

    async def interaction_check(self, interaction):
        if self.owner_id is not None and interaction.user.id != self.owner_id:
            await private_reply(interaction, "Este painel pertence a outra pessoa. Abra sua própria mão ou mesa.")
            return False
        if self.table is not None:
            if (interaction.guild is None or interaction.guild.id != self.table.guild_id
                    or self.table.status not in ("lobby", "playing")):
                await private_reply(interaction, "Esta mesa já foi encerrada. Abra outra com `/six iniciar`.")
                return False
        return True

    async def on_error(self, error, item, interaction):
        if isinstance(error, (RuleError, EconomyError)):
            await private_reply(interaction, str(error))
            return
        log.error("Uno interaction failed", exc_info=(type(error), error, error.__traceback__))
        # A failed private image/message must not void an otherwise healthy match.
        await private_reply(interaction, "Não consegui atualizar este painel. Abra Ver minha mão ou `/six iniciar` novamente.")


class ActionButton(nextcord.ui.Button):
    def __init__(self, label, handler, *, style=nextcord.ButtonStyle.secondary, disabled=False, row=None):
        super().__init__(label=label, style=style, disabled=disabled, row=row)
        self.handler = handler

    async def callback(self, interaction):
        await self.handler(interaction)


class Choice(nextcord.ui.Select):
    def __init__(self, placeholder, options, handler, *, row=0, minimum=1, maximum=1):
        # Nextcord 3.2 can omit custom_id when a string select uses its default.
        super().__init__(custom_id=f"uno:{uuid.uuid4().hex}", placeholder=placeholder, options=options, row=row,
                         min_values=minimum, max_values=maximum)
        self.handler = handler

    async def callback(self, interaction):
        await self.handler(interaction, list(self.values))


class ChannelPanel(SafeView):
    def __init__(self, cog, channel, owner):
        super().__init__(cog, owner_id=owner.id)
        self.channel = channel
        self.add_item(ActionButton("＋ Criar nova mesa", self.create, style=nextcord.ButtonStyle.success))
        tables = cog.channel_tables(channel.id)
        if tables and staff(owner):
            options = [nextcord.SelectOption(label=f"Mesa de {t.members.get(t.host_id, t.host_id)}"[:100], value=t.id)
                       for t in tables]
            self.add_item(Choice("Encerrar uma mesa (staff)", options, self.close_table, row=1))

    async def create(self, interaction):
        await interaction.response.defer(ephemeral=True)
        table = await self.cog.create_table(self.channel, interaction.user)
        await private_reply(interaction, f"Mesa aberta: {table.thread.mention}")

    async def close_table(self, interaction, values):
        if not staff(interaction.user):
            raise RuleError("Só a equipe com Gerenciar Mensagens ou Gerenciar Tópicos pode encerrar mesas.")
        await interaction.response.defer(ephemeral=True)
        table = self.cog.tables.get(values[0])
        if table is None or table.channel_id != self.channel.id:
            raise RuleError("Esta mesa já foi encerrada.")
        async with table.lock:
            await self.cog.cancel(table, f"Mesa encerrada pela equipe (<@{interaction.user.id}>); apostas devolvidas.")
        await private_reply(interaction, "Mesa encerrada.")


class InviteView(SafeView):
    def __init__(self, cog, table):
        super().__init__(cog, table, timeout=None)
        self.add_item(ActionButton("Entrar", self.join, style=nextcord.ButtonStyle.success))

    async def join(self, interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog.lobby_action(self.table, interaction.user, "join")
        await private_reply(interaction, f"Você está na mesa: {self.table.thread.mention}")


class LobbyView(InviteView):
    def __init__(self, cog, table):
        super().__init__(cog, table)
        join_button = self.children[0]
        self.remove_item(join_button)
        join_button.row = 4
        self.add_item(join_button)
        for label, action, style in (("Sair", "leave", nextcord.ButtonStyle.secondary),
                                     ("Começar", "start", nextcord.ButtonStyle.primary),
                                     ("Cancelar", "cancel", nextcord.ButtonStyle.danger)):
            async def invoke(interaction, action=action):
                await interaction.response.defer(ephemeral=True)
                await self.cog.lobby_action(self.table, interaction.user, action)
                await private_reply(interaction, {"leave": "Você saiu da mesa.", "start": "Partida iniciada!",
                                                 "cancel": "Mesa cancelada."}[action])
            self.add_item(ActionButton(label, invoke, style=style, row=4))
        options = [nextcord.SelectOption(label=title, value=key, description=description,
                                        default=getattr(table.rules, key)) for key, title, description in RULE_OPTIONS]
        self.add_item(Choice("Regras da casa", options, self.set_rules, minimum=0, maximum=5))
        self.add_item(Choice("Quantidade de vencedores", [nextcord.SelectOption(label=f"{n} vencedor(es)", value=str(n),
            default=table.winners == n) for n in range(1, 4)], self.set_winners, row=1))
        self.add_item(Choice("Aposta por pessoa", [nextcord.SelectOption(
            label=f"{n:,} D$ por pessoa" if n else "Sem aposta (casual)", value=str(n), default=table.stake == n)
            for n in (0, 100, 1000, 10000)], self.set_stake, row=2))
        self.add_item(Choice("Baralho da mesa", [nextcord.SelectOption(label=label, value=key,
            default=table.deck == key) for key, label in DECKS.items()], self.set_deck, row=3))

    async def set_rules(self, interaction, values):
        await self.configure(interaction, "rules", Rules(**{key: key in values for key, _, _ in RULE_OPTIONS}))

    async def set_winners(self, interaction, values):
        await self.configure(interaction, "winners", int(values[0]))

    async def set_stake(self, interaction, values):
        await self.configure(interaction, "stake", int(values[0]))

    async def set_deck(self, interaction, values):
        if values[0] not in DECKS:
            raise RuleError("Baralho inválido. Escolha Normal, Meme ou Overwatch.")
        await self.configure(interaction, "deck", values[0])

    async def configure(self, interaction, field_name, value):
        await interaction.response.defer(ephemeral=True)
        async with self.table.lock:
            if self.table.status != "lobby" or interaction.user.id != self.table.host_id:
                raise RuleError("Só o anfitrião pode configurar a mesa antes do início.")
            setattr(self.table, field_name, value)
            if field_name != "deck":
                self.table.ready = {self.table.host_id}
            await self.cog.refresh_lobby(self.table)
        await private_reply(interaction, f"Baralho escolhido: {DECKS[value]}." if field_name == "deck" else
                            "Configuração atualizada. Os demais jogadores precisam clicar em Entrar novamente para aceitar.")


class GameView(SafeView):
    def __init__(self, cog, table):
        super().__init__(cog, table, timeout=None)
        self.add_item(ActionButton("Ver minha mão", self.hand, style=nextcord.ButtonStyle.primary))
        self.add_item(ActionButton("Regras", self.rules))
        now = cog.clock()
        deadlines = table.game.uno_pending
        self.uno_display = tuple(sorted((uid, now < deadline) for uid, deadline in deadlines.items()))
        self.add_item(ActionButton("Gritar Uno!", self.call_uno, style=nextcord.ButtonStyle.success,
                                   disabled=not any(now < deadline for deadline in deadlines.values())))
        self.add_item(ActionButton("Pegar! (+2)", self.catch, style=nextcord.ButtonStyle.danger,
                                   disabled=not any(now >= deadline for deadline in deadlines.values())))
        if table.game.challenge is not None:
            self.add_item(ActionButton("Desafiar +4", self.challenge, row=1))
            self.add_item(ActionButton("Aceitar compra", self.accept, row=1))

    async def hand(self, interaction):
        await self.cog.show_hand(interaction, self.table)

    async def rules(self, interaction):
        await private_reply(interaction, embed=rules_embed(self.table))

    async def call_uno(self, interaction):
        await self.cog.act(interaction, self.table, "call_uno")

    async def catch(self, interaction):
        await self.cog.act(interaction, self.table, "catch_uno")

    async def challenge(self, interaction):
        await self.cog.act(interaction, self.table, "challenge_draw_four")

    async def accept(self, interaction):
        await self.cog.act(interaction, self.table, "draw")


class HandView(SafeView):
    def __init__(self, cog, table, owner_id, *, page=0, selected=(), declare=False, color=None, target=None):
        super().__init__(cog, table, owner_id=owner_id)
        game = table.game
        self.revision = game.revision
        self.page = max(0, min(page, (len(game.hands[owner_id]) - 1) // 25))
        self.cards = list(game.hands[owner_id][self.page * 25:(self.page + 1) * 25])
        self.selected, self.declare, self.color, self.target = tuple(selected), declare, color, target
        if selected:
            self.add_item(ActionButton(f"Jogar ({len(selected)})", self.confirm, style=nextcord.ButtonStyle.success, row=0))
            self.add_item(ActionButton("Voltar", self.back, row=0))
            transferring = table.rules.seven_zero and any(c.uid in selected and c.value in ("7", "0")
                                                          for c in game.hands[owner_id])
            if len(game.hands[owner_id]) - len(selected) == 1 and not transferring:
                self.add_item(ActionButton("Uno declarado ✓" if declare else "Gritar Uno antes de jogar", self.predeclare,
                                           style=nextcord.ButtonStyle.success, row=0))
        else:
            options = [nextcord.SelectOption(label=card_label(card)[:100], value=card.uid) for card in self.cards]
            if options:
                self.add_item(Choice("Escolher carta(s)", options, self.select_cards,
                                    maximum=len(options) if table.rules.multiple_cards else 1))
            self.add_item(ActionButton("Comprar", self.draw, row=1))
            self.add_item(ActionButton("Passar", self.pass_turn, disabled=not game.can_pass(owner_id), row=1))
            if self.page:
                self.add_item(ActionButton("← Anterior", self.previous, row=2))
            if (self.page + 1) * 25 < len(game.hands[owner_id]):
                self.add_item(ActionButton("Próxima →", self.next_page, row=2))
            self.add_item(ActionButton("Atualizar mão", self.back, row=2))

    def validate(self):
        if self.table.status != "playing" or self.owner_id not in self.table.game.players:
            raise RuleError("Você não está jogando nesta mesa.")
        if self.revision != self.table.game.revision:
            raise RuleError("A mesa mudou. Clique em Atualizar mão ou abra Ver minha mão novamente.")

    async def select_cards(self, interaction, values):
        await self.cog.show_hand(interaction, self.table, page=self.page, selected=values,
                                 revision=self.revision, edit=True)

    async def back(self, interaction):
        await self.cog.show_hand(interaction, self.table, page=self.page, edit=True)

    async def previous(self, interaction):
        await self.cog.show_hand(interaction, self.table, page=self.page - 1, edit=True)

    async def next_page(self, interaction):
        await self.cog.show_hand(interaction, self.table, page=self.page + 1, edit=True)

    async def predeclare(self, interaction):
        await self.cog.show_hand(interaction, self.table, page=self.page, selected=self.selected,
                                 revision=self.revision, declare=True, edit=True)

    async def draw(self, interaction):
        await self.cog.act(interaction, self.table, "draw", revision=self.revision, hand=True)

    async def pass_turn(self, interaction):
        await self.cog.act(interaction, self.table, "pass_turn", revision=self.revision, hand=True)

    async def confirm(self, interaction, *, color=None, target=None):
        await interaction.response.defer(ephemeral=True)
        async with self.table.lock:
            self.validate()
            cards = [c for c in self.table.game.hands[self.owner_id] if c.uid in self.selected]
            if len(cards) != len(self.selected):
                raise RuleError("Seleção inválida. Abra sua mão novamente.")
            if any(c.value in ("wild", "wild4") for c in cards) and color is None:
                view = ColorView(self)
                await interaction.edit_original_message(embed=nextcord.Embed(title="Escolha a cor do coringa", color=GREEN),
                                                        attachments=[], view=view)
                return
            if self.table.rules.seven_zero and any(c.value == "7" for c in cards) and target is None:
                view = SwapView(self)
                await interaction.edit_original_message(embed=nextcord.Embed(title="Escolha com quem trocar a mão", color=GREEN),
                                                        attachments=[], view=view)
                return
        await self.cog.act(interaction, self.table, "play", revision=self.revision, hand=True,
                           card_ids=list(self.selected), color=color, target_id=target, declare_uno=self.declare)


class ColorView(SafeView):
    def __init__(self, hand):
        super().__init__(hand.cog, hand.table, owner_id=hand.owner_id)
        self.hand = hand
        for color in COLORS:
            async def choose(interaction, color=color):
                await self.hand.confirm(interaction, color=color)
            self.add_item(ActionButton(COLOR_NAMES[color], choose))
        self.add_item(ActionButton("Voltar", hand.back, row=1))


class SwapView(SafeView):
    def __init__(self, hand):
        super().__init__(hand.cog, hand.table, owner_id=hand.owner_id)
        self.hand = hand
        options = [nextcord.SelectOption(label=hand.table.members[player][:100], value=str(player))
                   for player in hand.table.game.players if player != hand.owner_id]
        self.add_item(Choice("Trocar de mão com...", options, self.choose))
        self.add_item(ActionButton("Voltar", hand.back, row=1))

    async def choose(self, interaction, values):
        await self.hand.confirm(interaction, target=int(values[0]))


def rules_embed(table):
    embed = nextcord.Embed(title="🃏 Regras desta mesa", color=0xF5CD47, description=(
        "Jogue uma carta da **mesma cor, número ou símbolo** do topo. Coringas escolhem a cor.\n"
        "Sem carta? **Compre 1**; se servir, jogue a carta comprada ou passe. Se não servir, passa automaticamente.\n"
        "Ao ficar com **1 carta**, você tem **3 segundos** para **Gritar Uno!**, ou pode declarar na confirmação "
        "antes de jogar. Depois desse prazo, qualquer outro jogador pode apertar **Pegar!** para fazer você "
        "comprar 2, até a próxima jogada/compra/passagem. Trocar mãos com 7/0 exige nova declaração.\n"
        "**+4:** use quando não tiver a cor da vez. Com desafio ativado, é possível blefar: se tinha a cor, "
        "o autor compra 4; se o desafio falhar, quem desafiou compra a dívida +2 e perde a vez.\n"
        "**60s por vez:** quem demora compra 1 e perde a vez; dívidas +2/+4 são compradas integralmente.\n"
        "O descarte volta embaralhado quando o monte acaba, preservando a carta do topo."
    ))
    embed.add_field(name="Regras configuradas", value="\n".join(
        f"{'✅' if getattr(table.rules, key) else '⬜'} **{title}** — {description}"
        for key, title, description in RULE_OPTIONS), inline=False)
    embed.add_field(name="Vencedores e moedas", value=(
        f"{table.winners} vencedor(es). Aposta: {table.stake:,} D$ por pessoa. O pote é dividido entre os vencedores, "
        "com sobras na ordem de chegada. Primeiro colocado: +30 D$; todos que jogarem até o fim: +5 D$.\n"
        "Partidas interrompidas são canceladas e as apostas devolvidas."), inline=False)
    return embed


class Uno(commands.Cog):
    def __init__(self, bot, storage=None, clock=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.clock = clock or time.monotonic
        self.tables = {}
        self.memberships = {}
        self.registry_lock = asyncio.Lock()
        self.recovered = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.recovered:
            self.storage.recover_uno_games()
            self.recovered = True
        if not self.tick.is_running():
            self.tick.start()

    def cog_unload(self):
        self.tick.cancel()
        for table in list(self.tables.values()):
            if table.status == "playing":
                self.storage.cancel_uno_game(table.id)
            table.status = "finished" if table.status == "finishing" else "cancelled"
            for view in (table.view, table.invite_view):
                if view:
                    view.stop()
            self.release(table)

    def channel_tables(self, channel_id):
        return [t for t in self.tables.values() if t.channel_id == channel_id and t.status in ("lobby", "playing")]

    @commands.command(cls=DualCommand, name="six", aliases=["uno"],
                      help="Abre o painel do Uno/Six: r.six iniciar, r.uno ou /six iniciar. Crie mesas públicas para 2–20 pessoas; mãos privadas, regras e apostas opcionais.")
    @commands.guild_only()
    async def six(self, ctx, action: str = "iniciar"):
        if action.lower() != "iniciar":
            raise EconomyError("Use `r.six iniciar`, `r.uno` ou `/six iniciar`.")
        channel = ctx.channel.parent if isinstance(ctx.channel, nextcord.Thread) else ctx.channel
        if not isinstance(channel, nextcord.TextChannel):
            await ctx.send("Abra a mesa em um canal de texto do servidor.")
            return
        tables = self.channel_tables(channel.id)
        embed = nextcord.Embed(title="🃏 Six · Uno neste canal", color=GREEN,
            description="\n".join(f"• Mesa de <@{t.host_id}> · {len(t.members)} jogador(es) · "
                f"{'aguardando' if t.status == 'lobby' else 'jogando'} · {t.thread.mention}" for t in tables)
                or "Nenhuma mesa aberta. Crie uma para jogar com o pessoal!")
        view = ChannelPanel(self, channel, ctx.author)
        kwargs = {"ephemeral": True} if getattr(ctx, "interaction", None) is not None else {}
        await ctx.send(embed=embed, view=view, **kwargs)

    async def create_table(self, channel, member):
        if member.bot:
            raise RuleError("Bots não podem participar.")
        permissions = channel.permissions_for(channel.guild.me)
        needed = ("view_channel", "send_messages", "embed_links", "attach_files", "create_public_threads",
                  "send_messages_in_threads", "read_message_history")
        if not all(getattr(permissions, name, False) for name in needed):
            raise RuleError("Preciso de Ver Canal, Enviar Mensagens, Inserir Links, Anexar Arquivos, "
                            "Ler Histórico, Criar Tópicos Públicos e Enviar Mensagens em Tópicos.")
        async with self.registry_lock:
            if member.id in self.memberships:
                raise RuleError("Você já participa de uma mesa. Saia dela antes de criar outra.")
            if len(self.channel_tables(channel.id)) >= 25:
                raise RuleError("Este canal já tem 25 mesas abertas. Aguarde uma terminar.")
            table = Table(uuid.uuid4().hex, channel.guild.id, channel.id, member.id,
                          {member.id: member.display_name}, ready={member.id}, created_at=self.clock())
            self.tables[table.id] = table
            self.memberships[member.id] = table.id
            try:
                table.invite_view = InviteView(self, table)
                table.invite = await channel.send(embed=nextcord.Embed(title="🃏 Mesa de Six · Uno", color=GREEN,
                    description=f"<@{member.id}> abriu uma mesa. Toque em Entrar para jogar."), view=table.invite_view)
                table.thread = await table.invite.create_thread(name=f"Uno - {member.display_name}"[:100], auto_archive_duration=1440)
                await self.refresh_lobby(table)
            except Exception:
                await self.cancel(table, "Não foi possível abrir a mesa. Confira as permissões do bot.")
                raise
            return table

    async def lobby_action(self, table, member, action):
        async with self.registry_lock, table.lock:
            if table.status != "lobby":
                raise RuleError("Esta mesa já começou ou foi encerrada.")
            if action == "join":
                if member.bot:
                    raise RuleError("Bots não podem participar.")
                other = self.memberships.get(member.id)
                if other and other != table.id:
                    raise RuleError("Você já participa de outra mesa.")
                if len(table.members) >= 20 and member.id not in table.members:
                    raise RuleError("Esta mesa está cheia (20 jogadores).")
                if table.stake and self.storage.balance(member.id) < table.stake:
                    raise RuleError("Você não tem saldo para aceitar esta aposta.")
                table.members[member.id] = member.display_name
                table.ready.add(member.id)
                self.memberships[member.id] = table.id
            elif action == "leave":
                if member.id not in table.members:
                    raise RuleError("Você não está nesta mesa.")
                table.members.pop(member.id)
                table.ready.discard(member.id)
                self.memberships.pop(member.id, None)
                if not table.members:
                    await self.cancel(table, "Mesa encerrada: todos saíram.")
                    return
                if table.host_id == member.id:
                    table.host_id = next(iter(table.members))
            elif action == "cancel":
                if member.id != table.host_id and not staff(member):
                    raise RuleError("Só o anfitrião ou a equipe pode cancelar a mesa.")
                await self.cancel(table, "Mesa cancelada.")
                return
            elif action == "start":
                if member.id != table.host_id:
                    raise RuleError("Só o anfitrião pode começar.")
                if len(table.members) < 2:
                    raise RuleError("São necessários pelo menos 2 jogadores.")
                if not 1 <= table.winners < len(table.members):
                    raise RuleError("Escolha menos vencedores do que jogadores.")
                if table.ready != set(table.members):
                    raise RuleError("Todos precisam clicar em Entrar para aceitar as configurações atuais.")
                game = UnoGame(list(table.members), rules=replace(table.rules), winner_count=table.winners, now=self.clock())
                self.storage.start_uno_game(table.id, list(table.members), table.stake)
                table.game, table.status = game, "playing"
                try:
                    await self.disable_invite(table)
                    await self.publish(table)
                except Exception:
                    await self.cancel(table, "Não consegui iniciar a partida; apostas devolvidas.")
                    raise
                return
            await self.refresh_lobby(table)

    async def refresh_lobby(self, table):
        embed = nextcord.Embed(title="🃏 Mesa de Six · Uno", color=0xF5CD47,
            description=f"{len(table.members)}/20 jogadores · 60s por vez · o anfitrião começa quando quiser\n\n" +
                "\n".join(f"{'✅' if uid in table.ready else '⏳'} <@{uid}>" + (" · 👑 anfitrião" if uid == table.host_id else "")
                           for uid in table.members))
        embed.add_field(name="Configuração", value=f"Baralho **{DECKS[table.deck]}** · {table.winners} vencedor(es) · " +
                        (f"{table.stake:,} D$ por pessoa" if table.stake else "Sem aposta (casual)"), inline=False)
        embed.add_field(name="Regras da casa", value=", ".join(title for key, title, _ in RULE_OPTIONS
                        if getattr(table.rules, key)) or "Clássicas, sem desafio +4", inline=False)
        embed.set_footer(text="Entrar aceita regras e aposta. Alterações exigem novo aceite. Lobby expira em 15 min.")
        view = LobbyView(self, table)
        if table.message is None:
            table.message = await table.thread.send(embed=embed, view=view)
        else:
            await table.message.edit(embed=embed, view=view)
        if table.view:
            table.view.stop()
        table.view = view

    async def disable_invite(self, table):
        if table.invite_view:
            for item in table.invite_view.children:
                item.disabled = True
            table.invite_view.stop()
        if table.invite:
            await table.invite.edit(view=table.invite_view)

    def game_embed(self, table):
        game = table.game
        if game.finished:
            description = "\n".join(f"{'🏆' if index == 0 else '🏅'} {index + 1}º — <@{uid}>" for index, uid in enumerate(game.winners))
            embed = nextcord.Embed(title="🃏 Six · Uno — partida encerrada", color=GREEN,
                description=description + "\n\n+30 D$ para o campeão e +5 D$ para cada participante.\nAbra outra mesa com `/six iniciar`.")
            if table.stake:
                embed.add_field(name="Pote dividido", value=f"{table.stake * len(table.members):,} D$ entre os vencedores.")
        else:
            remaining = math.ceil(max(0, game.turn_deadline - self.clock()))
            deadline = math.ceil(time.time() + remaining)
            embed = nextcord.Embed(title="🃏 Six · Uno", color=GREEN,
                description=f"Vez de <@{game.current_player}> · termina <t:{deadline}:R>\n"
                f"Cor da vez: **{COLOR_NAMES[game.current_color]}** · {'↻' if game.direction == 1 else '↺'}\n"
                f"{game.last_action}")
            for offset in range(0, len(game.players), 10):
                embed.add_field(name="Jogadores" if offset == 0 else "Jogadores (continuação)", value="\n".join(
                    f"{'▶' if uid == game.current_player else '•'} <@{uid}> · {len(game.hands[uid])} carta(s)"
                    + (" · Uno!" if uid in game.uno_called else "") for uid in game.players[offset:offset + 10]), inline=False)
            if game.winners:
                embed.add_field(name="Já terminaram", value=", ".join(f"<@{uid}>" for uid in game.winners))
            if game.pending_draw:
                embed.add_field(name="Compra pendente", value=f"+{game.pending_draw} cartas. " +
                    ("Você pode empilhar +2/+4." if table.rules.stack_draw else "Compre para passar a vez."), inline=False)
            if game.uno_pending:
                embed.add_field(name="Última carta", value="Grite Uno em até 3 segundos; depois os outros podem usar Pegar!", inline=False)
            if game.challenge:
                embed.add_field(name="Desafio +4", value="O próximo jogador pode aceitar a compra ou chamar o blefe.", inline=False)
            embed.set_footer(text=f"Baralho {DECKS[table.deck]} • Ver minha mão abre suas cartas só para você • 60s por vez")
        embed.add_field(name="Última carta na mesa", value=card_label(game.top), inline=False)
        embed.set_image(url="attachment://uno-top.png")
        return embed

    async def publish(self, table, *, open_uno=()):
        game = table.game
        if game.finished:
            table.receipt = self.storage.finish_uno_game(table.id, list(game.winners))
            if table.receipt["status"] != "settled":
                await self.cancel(table, "Esta partida já foi cancelada; apostas devolvidas.")
                return
            table.status = "finishing"
            table.retry_at = self.clock() + 5
        data = await asyncio.to_thread(render_card, game.top, deck=table.deck)
        for uid in open_uno:
            if uid in game.uno_pending:
                game.uno_pending[uid] = self.clock() + UNO_SECONDS
        view = None if game.finished else GameView(self, table)
        try:
            await table.message.edit(embed=self.game_embed(table), view=view, attachments=[],
                                     file=nextcord.File(data, filename="uno-top.png"))
        except nextcord.HTTPException:
            if not game.finished:
                raise
            # If the old board was removed, publish the already-settled receipt once.
            embed = self.game_embed(table)
            embed.set_image(url=None)
            table.message = await table.thread.send(embed=embed)
        # The visible board starts the full call window, excluding upload latency.
        for uid in open_uno:
            if uid in game.uno_pending:
                game.uno_pending[uid] = self.clock() + UNO_SECONDS
        if table.view:
            table.view.stop()
        table.view = view
        table.uno_display = view.uno_display if view else ()
        if game.finished:
            table.status = "finished"
            self.release(table)

    def uno_display(self, table):
        return tuple(sorted((uid, self.clock() < deadline) for uid, deadline in table.game.uno_pending.items()))

    def release(self, table):
        for uid in table.members:
            if self.memberships.get(uid) == table.id:
                self.memberships.pop(uid, None)
        self.tables.pop(table.id, None)

    async def cancel(self, table, reason):
        if table.status == "finishing":
            # Rewards already committed: do not misreport a refund after victory.
            if table.view:
                table.view.stop()
            table.status = "finished"
            self.release(table)
            return
        if table.status not in ("lobby", "playing"):
            return
        if table.status == "playing":
            self.storage.cancel_uno_game(table.id)
        table.status = "cancelled"
        self.release(table)
        if table.view:
            table.view.stop()
        try:
            await self.disable_invite(table)
            if table.message:
                await table.message.edit(embed=nextcord.Embed(title="🃏 Mesa encerrada", description=reason, color=0xE35D6A),
                                         view=None, attachments=[])
        except nextcord.HTTPException:
            log.warning("Could not update cancelled Uno table %s", table.id)

    async def show_hand(self, interaction, table, *, edit=False, revision=None, **options):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        async with table.lock:
            if table.status != "playing" or interaction.user.id not in table.game.players:
                raise RuleError("Só jogadores desta partida podem ver a própria mão.")
            if revision is not None and revision != table.game.revision:
                raise RuleError("A mesa mudou. Abra sua mão novamente.")
            await self.send_hand(interaction, table, edit=edit, **options)

    async def send_hand(self, interaction, table, *, edit=False, **options):
        # Use the same discard order as the engine for a multi-selection preview.
        if options.get("selected"):
            by_id = {c.uid: c for c in table.game.hands[interaction.user.id]}
            selected_ids = tuple(options["selected"])
            if any(uid not in by_id for uid in selected_ids):
                raise RuleError("Esta seleção já saiu da sua mão. Abra sua mão novamente.")
            legal = {c.uid for c in table.game.legal_cards(interaction.user.id)}
            first = next((uid for uid in selected_ids if uid in legal), None)
            if first is not None:
                options["selected"] = (first, *(uid for uid in selected_ids if uid != first))
        view = HandView(self, table, interaction.user.id, **options)
        by_id = {c.uid: c for c in table.game.hands[interaction.user.id]}
        selected = [card_label(by_id[uid]) for uid in view.selected]
        embed = nextcord.Embed(title=f"Sua mão ({len(table.game.hands[interaction.user.id])})", color=GREEN,
            description=("Ordem da jogada: " + " → ".join(selected) if selected else "Escolha uma carta para revisar e confirmar a jogada.") +
            ("\n✅ Uno será declarado ao jogar." if view.declare else ""))
        pages = max(1, math.ceil(len(table.game.hands[interaction.user.id]) / 25))
        embed.set_footer(text=f"Baralho {DECKS[table.deck]} • Página {view.page + 1}/{pages} • Só você pode ver estas cartas")
        embed.set_image(url="attachment://uno-hand.png")
        data = await asyncio.to_thread(render_hand, view.cards, view.selected, deck=table.deck)
        kwargs = dict(embed=embed, view=view, file=nextcord.File(data, filename="uno-hand.png"))
        if edit:
            await interaction.edit_original_message(content=None, attachments=[], **kwargs)
        else:
            await private_reply(interaction, **kwargs)

    async def act(self, interaction, table, action, *, revision=None, hand=False, **kwargs):
        received_at = self.clock()
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        async with table.lock:
            if table.status != "playing":
                raise RuleError("Esta partida já terminou.")
            if revision is not None and revision != table.game.revision:
                raise RuleError("A mesa mudou. Abra sua mão novamente para jogar.")
            now = self.clock()
            try:
                if now >= table.game.turn_deadline:
                    table.game.timeout(now=now)
                    await self.publish(table)
                    raise RuleError("O tempo da vez acabou. Abra sua mão novamente.")
                # A timely Uno click must not expire while waiting for an image upload.
                action_time = received_at if action == "call_uno" else now
                old_windows = dict(table.game.uno_pending)
                getattr(table.game, action)(interaction.user.id, now=action_time, **kwargs)
                new_windows = [uid for uid, deadline in table.game.uno_pending.items()
                               if old_windows.get(uid) != deadline]
                await self.publish(table, open_uno=new_windows)
            except (RuleError, EconomyError):
                raise
            except Exception:
                if table.status != "finishing":
                    await self.cancel(table, "Não consegui atualizar a partida; apostas devolvidas.")
                raise
            if hand:
                if table.status == "playing" and interaction.user.id in table.game.players:
                    await self.send_hand(interaction, table, edit=True)
                else:
                    await interaction.edit_original_message(content="Você terminou suas cartas! Confira o resultado na mesa.",
                                                            embed=None, attachments=[], view=None)
            else:
                await private_reply(interaction, table.game.last_action)

    @tasks.loop(seconds=0.5)
    async def tick(self):
        for table in list(self.tables.values()):
            async with table.lock:
                try:
                    if table.status == "lobby" and self.clock() >= table.created_at + LOBBY_SECONDS:
                        await self.cancel(table, "O lobby expirou após 15 minutos. Abra outra mesa com `/six iniciar`.")
                    elif table.status == "finishing" and self.clock() >= table.retry_at:
                        await self.publish(table)
                    elif table.status == "playing":
                        if self.clock() >= table.game.turn_deadline:
                            table.game.timeout(now=self.clock())
                            await self.publish(table)
                        elif table.uno_display != self.uno_display(table):
                            # Replace controls at the 3-second boundary without reuploading the card image.
                            view = GameView(self, table)
                            await table.message.edit(view=view)
                            if table.view:
                                table.view.stop()
                            table.view, table.uno_display = view, view.uno_display
                except Exception:
                    log.exception("Uno timer failed for %s", table.id)
                    if table.status != "finishing":
                        await self.cancel(table, "A mesa foi interrompida; apostas devolvidas.")

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        for table in list(self.tables.values()):
            if table.thread and table.thread.id == thread.id:
                async with table.lock:
                    await self.cancel(table, "O tópico da mesa foi removido; apostas devolvidas.")


def setup(bot):
    bot.add_cog(Uno(bot))
