import logging
import math
import os
import time

import nextcord
from dotenv import load_dotenv
from nextcord.ext import commands

load_dotenv()

from db import EconomyError, database
from cogs.command_support import DualCommand, slash_name

log = logging.getLogger(__name__)


def error_message(error, usage, *, now=None):
    original = error
    while hasattr(original, "original"):
        original = original.original
    if isinstance(original, EconomyError):
        return str(original)
    if isinstance(original, commands.NoPrivateMessage):
        return "Use esse comando em um servidor."
    if isinstance(original, commands.MissingPermissions):
        return "Você precisa ser administrador para usar esse comando."
    if isinstance(original, commands.UserInputError):
        return f"Argumentos inválidos. Use: `{usage}`"
    if isinstance(original, commands.CommandOnCooldown):
        retry_at = math.ceil((time.time() if now is None else now) + original.retry_after)
        return f"Aguarde: você poderá tentar novamente <t:{retry_at}:R>."
    if isinstance(original, commands.CheckFailure):
        return "Você não pode usar esse comando aqui."
    log.error("Command failed", exc_info=(type(original), original, original.__traceback__))
    return "Não foi possível concluir o comando. Tente novamente mais tarde."


def create_bot():
    intents = nextcord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix="r.", intents=intents, help_command=None,
                       allowed_mentions=nextcord.AllowedMentions.none())
    for extension in ("economy", "leaderboard", "games", "social", "activities", "marriage", "roleplay", "sendmessage", "tickets", "missions", "confessions", "quiz"):
        bot.load_extension(f"cogs.{extension}")

    @bot.event
    async def on_ready():
        log.info("Logado como %s - %s", bot.user.name, bot.user.id)

    @bot.command(cls=DualCommand, help="Verifica se o bot está online.")
    async def ping(ctx):
        await ctx.send("Pong!")

    @bot.command(cls=DualCommand, name="help", help="Lista os comandos ou mostra sua ajuda: r.help [comando] ou /help.")
    async def help_command(ctx, *, command: str = None):
        embed = nextcord.Embed(title="Comandos do Ralsei", color=0x77E5BC)
        if command:
            name = command.strip().removeprefix("r.").removeprefix("/")
            if name == "profile view":
                name = "profile"
            target = bot.get_command(name)
            if target is None:
                await ctx.send("Comando não encontrado. Use `r.help` ou `/help` para ver a lista.")
                return
            embed.title = f"Ajuda: {target.qualified_name}"
            embed.description = target.help
            embed.add_field(name="Prefixo", value=f"`r.{target.qualified_name} {target.signature}`", inline=False)
            embed.add_field(name="Slash", value=f"`/{slash_name(target)}` — preencha as opções no Discord.", inline=False)
            if target.aliases:
                parent = f"{target.parent.qualified_name} " if target.parent else ""
                embed.add_field(name="Aliases do prefixo", value=", ".join(f"`r.{parent}{alias}`" for alias in target.aliases), inline=False)
        else:
            embed.description = ("Use **r.** ou **/**. Ex.: `r.mines 100 5` ou `/mines amount:100 mine_count:5`.\n"
                                 "Veja detalhes com `r.help mines` ou `/help command:mines`.\n"
                                 "Os aliases continuam disponíveis com o prefixo r.; cooldowns são compartilhados.")
            for target in sorted(bot.walk_commands(), key=lambda item: item.qualified_name):
                if len(embed.fields) == 25:
                    await ctx.send(embed=embed)
                    embed = nextcord.Embed(title="Comandos do Ralsei (continuação)", color=0x77E5BC)
                embed.add_field(name=f"r.{target.qualified_name} · /{slash_name(target)}",
                                value=target.short_doc[:200] or "Veja a ajuda do comando.", inline=False)
        await ctx.send(embed=embed)

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Defina DISCORD_TOKEN no arquivo .env antes de iniciar o bot.")
    recovered = database.recover_bets()
    if recovered:
        log.info("Reembolsadas %s apostas interrompidas", recovered)
    create_bot().run(token)
