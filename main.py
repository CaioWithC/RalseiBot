import logging
import math
import os
import time

import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands


load_dotenv()

from db import EconomyError, database
from cogs.command_support import DualCommand, ModerationError, CommandDisabledError, slash_name
from cogs.help_system import build_command_detail_embed, build_home_embed, HelpView
from web.command_data import COMMAND_METADATA

log = logging.getLogger(__name__)


class RalseiBot(commands.Bot):
    async def get_prefix(self, message):
        default = self.command_prefix
        if message and getattr(message, "guild", None):
            try:
                prefix = database.get_guild_prefix(message.guild.id)
                if prefix and prefix != default:
                    return (prefix, default)
            except Exception:
                pass
        return default


def error_message(error, usage, *, now=None):
    original = error
    while hasattr(original, "original"):
        original = original.original
    if isinstance(original, (EconomyError, ModerationError, CommandDisabledError)):
        return str(original)
    if isinstance(original, commands.NoPrivateMessage):
        return "Use esse comando em um servidor."
    if isinstance(original, commands.MissingPermissions):
        if original.missing_permissions == ["administrator"]:
            return "Você precisa ser administrador para usar esse comando."
        return "Você precisa das permissões: " + permission_names(original.missing_permissions) + "."
    if isinstance(original, commands.BotMissingPermissions):
        return "Preciso das permissões: " + permission_names(original.missing_permissions) + "."
    if isinstance(original, nextcord.Forbidden):
        return "O Discord recusou a ação. Verifique minhas permissões e a hierarquia dos cargos."
    if isinstance(original, nextcord.NotFound):
        return "O membro, canal ou mensagem não foi encontrado."
    if isinstance(original, commands.UserInputError):
        return f"Argumentos inválidos. Use: `{usage}`"
    if isinstance(original, commands.CommandOnCooldown):
        retry_at = math.ceil((time.time() if now is None else now) + original.retry_after)
        return f"Aguarde: você poderá tentar novamente <t:{retry_at}:R>."
    if isinstance(original, commands.CheckFailure):
        return "Você não pode usar esse comando aqui."
    log.error("Command failed", exc_info=(type(original), original, original.__traceback__))
    return "Não foi possível concluir o comando. Tente novamente mais tarde."


def permission_names(names):
    labels = {"ban_members": "Banir Membros", "kick_members": "Expulsar Membros",
              "moderate_members": "Moderar Membros", "manage_channels": "Gerenciar Canais",
              "manage_roles": "Gerenciar Cargos", "manage_messages": "Gerenciar Mensagens",
              "read_message_history": "Ler Histórico de Mensagens", "view_channel": "Ver Canal"}
    return ", ".join(labels.get(name, name) for name in names)


def create_bot():
    intents = nextcord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = RalseiBot(command_prefix="r.", intents=intents, help_command=None,
                    allowed_mentions=nextcord.AllowedMentions.none())

    @bot.check
    async def check_command_enabled(ctx):
        if ctx.guild and ctx.command:
            root_name = ctx.command.root_parent.name if ctx.command.root_parent else ctx.command.name
            if root_name not in ("help", "ping", "sync"):
                cat_key = COMMAND_METADATA.get(root_name, {}).get("cat")
                if database.is_command_disabled(str(ctx.guild.id), root_name, category_key=cat_key) or database.is_command_disabled(str(ctx.guild.id), ctx.command.qualified_name, category_key=cat_key):
                    raise CommandDisabledError(ctx.command.qualified_name)
        return True

    for extension in ("economy", "music", "leaderboard", "games", "poker", "social", "activities", "marriage", "roleplay", "sendmessage", "tickets", "missions", "confessions", "quiz", "uno", "moderation", "ai", "userinfo", "tarot", "anilist"):
        bot.load_extension(f"cogs.{extension}")

    @bot.event
    async def on_ready():
        log.info("Logado como %s - %s", bot.user.name, bot.user.id)

    @bot.command(cls=DualCommand, help="Verifica se o bot está online.")
    async def ping(ctx):
        await ctx.send("Pong!")

    @bot.command(cls=DualCommand, name="help", help="Lista os comandos ou mostra sua ajuda: r.help [comando] ou /help.")
    async def help_command(ctx, *, command: str = None):
        is_interaction = getattr(ctx, "interaction", None) is not None
        kwargs = {"ephemeral": True} if is_interaction else {}
        if command:
            name = command.strip().removeprefix("r.").removeprefix("/")
            if name == "profile view":
                name = "profile"
            if name in ("six iniciar", "uno iniciar"):
                name = "six"
            target = bot.get_command(name)
            if target is None:
                await ctx.send("Comando não encontrado. Use `r.help` ou `/help` para ver a lista.", **kwargs)
                return
            embed = build_command_detail_embed(target, ctx.author)
            await ctx.send(embed=embed, **kwargs)
        else:
            embed = build_home_embed(bot, ctx.author)
            view = HelpView(bot, ctx.author.id)
            message = await ctx.send(embed=embed, view=view, **kwargs)
            view.message = message

    @bot.command(cls=DualCommand, name="site", help="Visite o nosso site.")
    async def site(ctx):
        await ctx.send("https://ralseibot.vercel.app/")

    @bot.command(cls=DualCommand, name="sync",
                 help="Administrador: sincroniza os comandos de barra com o Discord.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def sync_commands(ctx):
        await bot.sync_application_commands(
            guild_id=None, register_new=True, update_known=True, delete_unknown=True
        )
        count = len(bot.get_all_application_commands())
        await ctx.send(f"Sincronizados {count} comandos de barra globalmente.")

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        now = (ctx.message.edited_at or ctx.message.created_at).timestamp()
        if getattr(ctx, "interaction", None) is not None:
            await ctx.send(error_message(error, f"/{slash_name(ctx.command)}", now=now), ephemeral=True)
        else:
            await ctx.send(error_message(error, f"r.{ctx.command.qualified_name} {ctx.command.signature}", now=now))

    @bot.event
    async def on_application_command_error(interaction, error):
        command = interaction.application_command
        usage = f"/{command.qualified_name}" if command else "/help"
        message = error_message(error, usage, now=interaction.created_at.timestamp())
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # Nextcord registers global application commands automatically on connection.
    bot.load_extension("cogs.slash_commands")
    return bot


# Top-level WSGI exports for Vercel deployment detection
from api.index import app as _index_app
app = _index_app
application = app
handler = app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Defina DISCORD_TOKEN no arquivo .env antes de iniciar o bot.")
    recovered = database.recover_bets()
    if recovered:
        log.info("Reembolsadas %s apostas interrompidas", recovered)
    create_bot().run(token)
