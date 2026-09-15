"""Moderation shared by prefix and slash commands."""
import asyncio
import re
from datetime import timedelta

import nextcord
from nextcord.ext import commands

from cogs.command_support import DualCommand, ModerationError
from db import database


def parse_duration(value):
    match = re.fullmatch(r"([0-9]{1,8})([smhd])", value.strip().lower())
    if match is None:
        raise ModerationError("Use uma duração como 30s, 10m, 2h ou 7d (máximo: 28d).")
    seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]
    if not 1 <= seconds <= 28 * 86400:
        raise ModerationError("A duração deve ser de pelo menos 1 segundo e no máximo 28 dias.")
    return timedelta(seconds=seconds)


def audit_reason(ctx, reason):
    reason = (reason or "Não informado").strip() or "Não informado"
    if len(reason) > 400:
        raise ModerationError("O motivo pode ter até 400 caracteres.")
    return f"Moderador: {ctx.author.id} | {reason}"


def check_target(ctx, member, *, timeout=False):
    if member.guild.id != ctx.guild.id:
        raise ModerationError("Escolha um membro deste servidor.")
    if member.id in (ctx.author.id, ctx.guild.me.id, ctx.guild.owner_id):
        raise ModerationError("Você não pode aplicar essa ação em si mesmo, no bot ou no dono do servidor.")
    if ctx.author.id != ctx.guild.owner_id and member.top_role >= ctx.author.top_role:
        raise ModerationError("Seu cargo mais alto precisa estar acima do cargo do membro.")
    if member.top_role >= ctx.guild.me.top_role:
        raise ModerationError("Meu cargo mais alto precisa estar acima do cargo do membro.")
    if timeout and (member.bot or member.guild_permissions.administrator):
        raise ModerationError("O Discord não permite aplicar timeout em bots ou administradores.")


LOCK_FLAGS = ("send_messages", "send_messages_in_threads", "create_public_threads", "create_private_threads")


class Moderation(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.channel_locks = {}

    async def text_channel(self, ctx, channel, *permissions):
        channel = channel or ctx.channel
        if not isinstance(channel, nextcord.TextChannel) or channel.guild.id != ctx.guild.id:
            raise ModerationError("Use um canal de texto deste servidor; tópicos não são aceitos.")
        # Check the selected channel, not the channel where the command was sent.
        for member, error in ((ctx.author, commands.MissingPermissions),
                              (ctx.guild.me, commands.BotMissingPermissions)):
            effective = channel.permissions_for(member)
            missing = [name for name in ("view_channel", *permissions) if not getattr(effective, name)]
            if missing:
                raise error(missing)
        return channel

    @commands.command(cls=DualCommand, aliases=["banir"],
                      help="Bane um membro. Uso: r.ban @membro [motivo]. Requer Banir Membros; preserva mensagens.")
    @commands.guild_only()
    @commands.has_guild_permissions(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    async def ban(self, ctx, member: nextcord.Member, *, reason: str = None):
        check_target(ctx, member)
        await ctx.guild.ban(member, reason=audit_reason(ctx, reason), delete_message_seconds=0)
        await ctx.send(f"Membro {member.id} banido.")

    @commands.command(cls=DualCommand, aliases=["desbanir"],
                      help="Remove um banimento pelo ID. Uso: r.unban ID [motivo]. Requer Banir Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    async def unban(self, ctx, user_id: str, *, reason: str = None):
        if not re.fullmatch(r"[0-9]{15,20}", user_id) or int(user_id) >= 2 ** 64:
            raise ModerationError("Informe um ID de usuário válido (ative o Modo Desenvolvedor para copiar o ID).")
        try:
            await ctx.guild.unban(nextcord.Object(id=int(user_id)), reason=audit_reason(ctx, reason))
        except nextcord.NotFound:
            raise ModerationError("Esse usuário não está banido neste servidor.") from None
        await ctx.send(f"Banimento de {user_id} removido.")

    @commands.command(cls=DualCommand, aliases=["expulsar"],
                      help="Expulsa um membro. Uso: r.kick @membro [motivo]. Requer Expulsar Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
    async def kick(self, ctx, member: nextcord.Member, *, reason: str = None):
        check_target(ctx, member)
        await member.kick(reason=audit_reason(ctx, reason))
        await ctx.send(f"Membro {member.id} expulso.")

    @commands.command(cls=DualCommand, aliases=["timeout", "silenciar"],
                      help="Aplica timeout: r.mute @membro 10m [motivo]. Aceita s/m/h/d, até 28d. Requer Moderar Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(moderate_members=True)
    @commands.bot_has_guild_permissions(moderate_members=True)
    async def mute(self, ctx, member: nextcord.Member, duration: str, *, reason: str = None):
        check_target(ctx, member, timeout=True)
        until = nextcord.utils.utcnow() + parse_duration(duration)
        await member.timeout(until, reason=audit_reason(ctx, reason))
        await ctx.send(f"Membro {member.id} silenciado até <t:{int(until.timestamp())}:F>.")

    @commands.command(cls=DualCommand, aliases=["desmutar"],
                      help="Remove o timeout: r.unmute @membro [motivo]. Requer Moderar Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(moderate_members=True)
    @commands.bot_has_guild_permissions(moderate_members=True)
    async def unmute(self, ctx, member: nextcord.Member, *, reason: str = None):
        check_target(ctx, member)
        await member.timeout(None, reason=audit_reason(ctx, reason))
        await ctx.send(f"Timeout do membro {member.id} removido.")

    async def change_lock(self, ctx, channel, reason, *, unlock):
        channel = await self.text_channel(ctx, channel, "manage_channels", "manage_roles")
        reason = audit_reason(ctx, reason)
        lock = self.channel_locks.setdefault(channel.id, asyncio.Lock())
        async with lock:
            # Fetch after acquiring the lock so successive commands don't reuse stale overwrites.
            channel = await ctx.guild.fetch_channel(channel.id)
            await self.text_channel(ctx, channel, "manage_channels", "manage_roles")
            previous = self.storage.channel_lock(ctx.guild.id, channel.id)
            if unlock and previous is None:
                raise ModerationError("Não há lock salvo pelo bot neste canal.")
            if not unlock and previous is not None:
                raise ModerationError("Este canal já tem um lock salvo. Use unlock para restaurar as permissões.")
            overwrite = channel.overwrites_for(ctx.guild.default_role)
            if unlock:
                for flag in LOCK_FLAGS:
                    setattr(overwrite, flag, previous[flag])
                await channel.set_permissions(ctx.guild.default_role,
                                              overwrite=None if overwrite.is_empty() else overwrite,
                                              reason=reason)
                self.storage.delete_channel_lock(ctx.guild.id, channel.id)
            else:
                previous = {flag: getattr(overwrite, flag) for flag in LOCK_FLAGS}
                # Save before the API request: even an interrupted request remains recoverable.
                self.storage.save_channel_lock(ctx.guild.id, channel.id, previous)
                for flag in LOCK_FLAGS:
                    setattr(overwrite, flag, False)
                try:
                    await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=reason)
                except (nextcord.Forbidden, nextcord.NotFound):
                    self.storage.delete_channel_lock(ctx.guild.id, channel.id)
                    raise
        if unlock:
            await ctx.send(f"Permissões anteriores de {channel.mention} restauradas.")
        else:
            await ctx.send(f"{channel.mention} bloqueado para @everyone. Administradores e permissões explícitas de cargos/membros podem continuar permitindo mensagens.")

    @commands.command(cls=DualCommand, aliases=["trancar"],
                      help="Bloqueia mensagens e tópicos para @everyone: r.lock [#canal] [motivo]. Requer Gerenciar Canais e Cargos.")
    @commands.guild_only()
    async def lock(self, ctx, channel: nextcord.TextChannel = None, *, reason: str = None):
        await self.change_lock(ctx, channel, reason, unlock=False)

    @commands.command(cls=DualCommand, aliases=["destrancar"],
                      help="Restaura as permissões anteriores ao lock: r.unlock [#canal] [motivo]. Requer Gerenciar Canais e Cargos.")
    @commands.guild_only()
    async def unlock(self, ctx, channel: nextcord.TextChannel = None, *, reason: str = None):
        await self.change_lock(ctx, channel, reason, unlock=True)

    @commands.command(cls=DualCommand, aliases=["limpar", "purge"],
                      help="Exclui de 1 a 100 mensagens anteriores ao comando: r.clear 10. Requer Gerenciar Mensagens e Ler Histórico.")
    @commands.guild_only()
    async def clear(self, ctx, amount: int):
        if not 1 <= amount <= 100:
            raise ModerationError("Escolha de 1 a 100 mensagens para excluir.")
        channel = await self.text_channel(ctx, None, "manage_messages", "read_message_history")
        # Never delete the slash deferred response, the invocation, or messages arriving later.
        boundary = ctx.interaction.created_at if getattr(ctx, "interaction", None) else ctx.message
        deleted = await channel.purge(limit=amount, before=boundary)
        await ctx.send(f"{len(deleted)} mensagem(ns) excluída(s).")

    @commands.command(cls=DualCommand, aliases=["modolento"],
                      help="Define o modo lento de 0 a 21600 segundos (0 desativa): r.slowmode 10 [#canal]. Requer Gerenciar Canais.")
    @commands.guild_only()
    async def slowmode(self, ctx, seconds: int, channel: nextcord.TextChannel = None, *, reason: str = None):
        if not 0 <= seconds <= 21600:
            raise ModerationError("Use de 0 a 21600 segundos; 0 desativa o modo lento.")
        channel = await self.text_channel(ctx, channel, "manage_channels")
        await channel.edit(slowmode_delay=seconds, reason=audit_reason(ctx, reason))
        await ctx.send(f"Modo lento de {channel.mention}: {seconds} segundo(s).")


def setup(bot):
    bot.add_cog(Moderation(bot))
