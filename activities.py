"""Rotating custom statuses and short reactions to successful admin commands."""
from dataclasses import dataclass
import logging
import math
import time

from aiohttp import ClientError
import nextcord
from nextcord.ext import commands, tasks

from command_support import DualCommand, slash_name
from db import EconomyError

log = logging.getLogger(__name__)
ROTATION_SECONDS = 60
ADMIN_REACTION_SECONDS = 30
MANUAL_ACTIVITY_SECONDS = 300
MIN_UPDATE_SECONDS = 10
MAX_ACTIVITY_LENGTH = 128

# Emoji are part of the text: Discord bot activities support name/state/type,
# while a separate activity emoji field is not available to bot accounts.
ACTIVITIES = (
    "💚 Caio é meu dono e meu orgulho!",
    "📚 {commands} comandos com r. e / | Use r.help ou /help",
    "✨ Meu dono Caio tem as melhores ideias!",
    "🏡 {server}",
    "🐯 Tenho guarda compartilhada com o Bru!",
    "🌍 Levando carinho a {guilds} servidor(es)!",
    "🎲 Slots, blackjack e mines: perca tudo!",
    "🐐 Feito com carinho pelo incrível Caio!",
    "⏱️ Online há {uptime} | {completed} comandos concluídos nesta sessão",
    "🎨 Seu perfil, seu estilo: r.profile | /profile view",
    "💚 Caio manda bem demais! Sou fã do meu dono.",
    "📡 Latência: {latency} | Pronto para ajudar!",
    "💰 DarkMoney, diversão e amigos. Esse é o meu reino!",
)


def one_line(text):
    return " ".join(text.split())


def status_text(text):
    text = one_line(text)
    return text if len(text) <= MAX_ACTIVITY_LENGTH else text[:MAX_ACTIVITY_LENGTH - 1] + "…"


@dataclass(frozen=True)
class ActivityOverride:
    text: str
    expires_at: float
    manual: bool = False


class Activities(commands.Cog):
    def __init__(self, bot, *, clock=time.monotonic):
        self.bot = bot
        self.clock = clock
        self.started_at = clock()
        self.completed_commands = 0
        self.rotation_index = 0
        self.current_text = None
        self.override = None
        self._showing_override = False
        self._next_rotation = 0
        self._last_attempt = -math.inf

    def rotation_text(self):
        guilds = [guild for guild in self.bot.guilds if not guild.unavailable]
        server = "Esperando novos amigos em um servidor!"
        if guilds:
            guild = guilds[(self.rotation_index // len(ACTIVITIES)) % len(guilds)]
            name = status_text(guild.name)[:80]
            server = (f"{name}: {guild.member_count:,} membros"
                      if guild.member_count is not None else f"Cuidando de {name}")
        minutes = max(0, int(self.clock() - self.started_at)) // 60
        days, hours = divmod(minutes // 60, 24)
        uptime = f"{days}d {hours}h {minutes % 60}min" if days else f"{hours}h {minutes % 60}min"
        latency = self.bot.latency
        latency = f"{round(latency * 1000)} ms" if math.isfinite(latency) else "conectando…"
        return status_text(ACTIVITIES[self.rotation_index % len(ACTIVITIES)].format(
            commands=sum(1 for _ in self.bot.walk_commands()), server=server,
            guilds=len(self.bot.guilds), uptime=uptime, latency=latency,
            completed=self.completed_commands,
        ))

    async def refresh(self):
        if not self.bot.is_ready() or self.bot.is_closed():
            return
        now = self.clock()
        if now - self._last_attempt < MIN_UPDATE_SECONDS:
            return
        override = self.override
        if override is not None and now >= override.expires_at:
            self.override = override = None
        if override is not None:
            text = override.text
        elif self.current_text is None or self._showing_override or now >= self._next_rotation:
            text = self.rotation_text()
        else:
            return

        if text != self.current_text:
            # A single worker publishes updates. Bursts of commands replace the
            # pending reaction instead of sending a presence per command.
            self._last_attempt = now
            try:
                await self.bot.change_presence(activity=nextcord.CustomActivity(name=text))
            except (ClientError, OSError, nextcord.ConnectionClosed, nextcord.HTTPException):
                log.warning("Could not update custom activity; will retry", exc_info=True)
                return
            self.current_text = text
        self._showing_override = override is not None
        if override is None:
            self.rotation_index += 1
            self._next_rotation = now + ROTATION_SECONDS

    @tasks.loop(seconds=5)
    async def update_activity(self):
        await self.refresh()

    @commands.Cog.listener()
    async def on_ready(self):
        # READY can happen again after reconnecting; keep only one worker and
        # restore the current override, if any, on the new connection.
        self.current_text = None
        if not self.update_activity.is_running():
            self.update_activity.start()

    def cog_unload(self):
        self.update_activity.cancel()

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.command_failed:
            return
        self.completed_commands += 1
        if ctx.guild is None or not ctx.author.guild_permissions.administrator:
            return
        if ctx.command.qualified_name == "activity":
            return
        now = self.clock()
        if self.override is not None and self.override.manual and now < self.override.expires_at:
            return
        name = ctx.command.qualified_name
        admin = one_line(ctx.author.display_name)[:40]
        command = f"/{slash_name(ctx.command)}" if getattr(ctx, "interaction", None) else f"r.{name}"

    @commands.command(cls=DualCommand, aliases=["atividade", "status"],
                      help="Administrador: r.activity <texto de até 128 caracteres> por 5 minutos. Use reset para retomar a rotação.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def activity(self, ctx, *, text: str):
        text = one_line(text)
        if text.lower() == "reset":
            self.override = None
            self._next_rotation = 0
            await ctx.send("Rotação automática de atividades retomada. A atualização aparece em até 10 segundos.")
            return
        if not 1 <= len(text) <= MAX_ACTIVITY_LENGTH:
            raise EconomyError("Use uma atividade com 1 a 128 caracteres, ou reset para retomar a rotação.")
        self.override = ActivityOverride(text, self.clock() + MANUAL_ACTIVITY_SECONDS, manual=True)
        await ctx.send("Atividade personalizada definida por 5 minutos para todos os servidores! "
                       "A atualização aparece em até 10 segundos. Use `r.activity reset` ou `/activity text:reset` para retomar a rotação.")


def setup(bot):
    bot.add_cog(Activities(bot))
