"""Moderation shared by prefix and slash commands."""
import asyncio
import re
from datetime import timedelta

import nextcord
from nextcord.ext import commands

from cogs.command_support import DualCommand, ModerationError
from db import database

COLOR_CONFIRM = 0xF1C40F
COLOR_DANGER = 0xED4245
COLOR_WARNING = 0xE67E22
COLOR_SUCCESS = 0x57F287
COLOR_INFO = 0x77E5BC
COLOR_CANCEL = 0x95A5A6
COLOR_TIMEOUT = 0x7F8C8D


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


def extract_force_flag(reason):
    if not reason:
        return None, False
    parts = reason.strip().split()
    flags = {"-y", "--yes", "-f", "--force", "--confirm"}
    force = False
    cleaned_parts = []
    for part in parts:
        if part.lower() in flags:
            force = True
        else:
            cleaned_parts.append(part)
    cleaned_reason = " ".join(cleaned_parts).strip() or None
    return cleaned_reason, force


def member_mention(target):
    if hasattr(target, "mention"):
        return target.mention
    return f"<@{target.id}>"


def member_name(target):
    if hasattr(target, "display_name"):
        return target.display_name
    if hasattr(target, "name"):
        return target.name
    return str(target.id)


def avatar_url(target):
    if hasattr(target, "display_avatar") and hasattr(target.display_avatar, "url"):
        return target.display_avatar.url
    if hasattr(target, "avatar") and hasattr(target.avatar, "url"):
        return target.avatar.url
    return None


LOCK_FLAGS = ("send_messages", "send_messages_in_threads", "create_public_threads", "create_private_threads")


class ModerationConfirmView(nextcord.ui.View):
    def __init__(self, author, *, on_confirm, success_embed=None, cancel_embed=None,
                 confirm_style=nextcord.ButtonStyle.danger, timeout=60):
        super().__init__(timeout=timeout)
        self.author = author
        self.on_confirm = on_confirm
        self.success_embed = success_embed
        self.cancel_embed = cancel_embed
        self.confirm_button.style = confirm_style
        self.message = None
        self.done = False
        self.error = None
        self.lock = asyncio.Lock()

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Apenas o moderador que executou o comando pode responder a esta confirmação.",
                ephemeral=True
            )
            return False
        return True

    async def confirm_action(self, interaction: nextcord.Interaction):
        await self.respond(interaction, confirmed=True)

    async def cancel_action(self, interaction: nextcord.Interaction):
        await self.respond(interaction, confirmed=False)

    @nextcord.ui.button(label="Confirmar", style=nextcord.ButtonStyle.danger, emoji="✅")
    async def confirm_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.confirm_action(interaction)

    @nextcord.ui.button(label="Cancelar", style=nextcord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await self.cancel_action(interaction)

    async def respond(self, interaction: nextcord.Interaction, *, confirmed: bool):
        if not await self.interaction_check(interaction):
            return
        if hasattr(interaction, "response") and hasattr(interaction.response, "defer"):
            try:
                await interaction.response.defer()
            except Exception:
                pass
        async with self.lock:
            if self.done:
                return
            self.done = True
            for child in self.children:
                child.disabled = True
            self.stop()

            if confirmed:
                try:
                    result = await self.on_confirm()
                    embed = result if isinstance(result, nextcord.Embed) else self.success_embed
                    await self._update_message(interaction, embed=embed, view=None)
                except Exception as error:
                    self.error = error
                    error_embed = nextcord.Embed(
                        title="❌ Falha na Execução",
                        description=f"Não foi possível concluir a ação: {error}",
                        color=COLOR_DANGER
                    )
                    await self._update_message(interaction, embed=error_embed, view=None)
            else:
                cancel_embed = self.cancel_embed or nextcord.Embed(
                    title="❌ Ação Cancelada",
                    description="A ação de moderação foi cancelada pelo moderador.",
                    color=COLOR_CANCEL
                )
                await self._update_message(interaction, embed=cancel_embed, view=None)

    async def _update_message(self, interaction: nextcord.Interaction, embed: nextcord.Embed, view):
        target_msg = getattr(interaction, "message", None) or self.message
        if target_msg and hasattr(target_msg, "edit"):
            await target_msg.edit(embed=embed, view=view)
        elif hasattr(interaction, "edit_original_message"):
            await interaction.edit_original_message(embed=embed, view=view)
        elif hasattr(interaction, "response") and hasattr(interaction.response, "edit_message"):
            await interaction.response.edit_message(embed=embed, view=view)

    async def on_timeout(self):
        async with self.lock:
            if self.done:
                return
            self.done = True
            for child in self.children:
                child.disabled = True
            if self.message and hasattr(self.message, "edit"):
                timeout_embed = nextcord.Embed(
                    title="⏱️ Confirmação Expirada",
                    description="O tempo limite para confirmação expirou (60s). Nenhuma ação foi realizada.",
                    color=COLOR_TIMEOUT
                )
                timeout_embed.set_footer(text="Ação expirada • Ralsei Moderation")
                try:
                    await self.message.edit(embed=timeout_embed, view=self)
                except Exception:
                    pass


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

    async def execute_with_confirmation(self, ctx, *, confirm_embed, success_embed, cancel_embed,
                                        on_confirm, confirm_style=nextcord.ButtonStyle.danger, force=False):
        if force:
            result = await on_confirm()
            embed = result if isinstance(result, nextcord.Embed) else success_embed
            return await ctx.send(embed=embed)

        view = ModerationConfirmView(
            ctx.author,
            on_confirm=on_confirm,
            success_embed=success_embed,
            cancel_embed=cancel_embed,
            confirm_style=confirm_style
        )
        msg = await ctx.send(embed=confirm_embed, view=view)
        view.message = msg
        return view

    @commands.command(cls=DualCommand, aliases=["banir"],
                      help="Bane um membro. Uso: r.ban @membro [motivo]. Requer Banir Membros; preserva mensagens.")
    @commands.guild_only()
    @commands.has_guild_permissions(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    async def ban(self, ctx, member: nextcord.Member, *, reason: str = None):
        check_target(ctx, member)
        clean_reason, force = extract_force_flag(reason)
        audit = audit_reason(ctx, clean_reason)
        display_reason = clean_reason or "Não informado"
        avatar = avatar_url(member)

        confirm_embed = nextcord.Embed(
            title="⚠️ Confirmação: Banir Membro",
            description=f"Tem certeza de que deseja banir {member_mention(member)} do servidor?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
        confirm_embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        if avatar:
            confirm_embed.set_thumbnail(url=avatar)
        confirm_embed.set_footer(text="Clique em Confirmar para aplicar o banimento • Expira em 60s")

        success_embed = nextcord.Embed(
            title="🔨 Membro Banido",
            description=f"O membro {member_mention(member)} foi banido com sucesso.",
            color=COLOR_DANGER,
            timestamp=nextcord.utils.utcnow()
        )
        success_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
        success_embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
        success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        success_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        if avatar:
            success_embed.set_thumbnail(url=avatar)
        success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"O banimento de {member_mention(member)} foi cancelado pelo moderador.",
            color=COLOR_CANCEL
        )

        async def do_ban():
            await ctx.guild.ban(member, reason=audit, delete_message_seconds=0)
            return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=success_embed,
            cancel_embed=cancel_embed,
            on_confirm=do_ban,
            confirm_style=nextcord.ButtonStyle.danger,
            force=force
        )

    @commands.command(cls=DualCommand, aliases=["desbanir"],
                      help="Remove um banimento pelo ID. Uso: r.unban ID [motivo]. Requer Banir Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(ban_members=True)
    @commands.bot_has_guild_permissions(ban_members=True)
    async def unban(self, ctx, user_id: str, *, reason: str = None):
        if not re.fullmatch(r"[0-9]{15,20}", user_id) or int(user_id) >= 2 ** 64:
            raise ModerationError("Informe um ID de usuário válido (ative o Modo Desenvolvedor para copiar o ID).")
        clean_reason, force = extract_force_flag(reason)
        audit = audit_reason(ctx, clean_reason)
        display_reason = clean_reason or "Não informado"

        confirm_embed = nextcord.Embed(
            title="⚠️ Confirmação: Desbanir Usuário",
            description=f"Tem certeza de que deseja remover o banimento do usuário `{user_id}`?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="👤 Usuário ID", value=f"`{user_id}`", inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        confirm_embed.set_footer(text="Clique em Confirmar para desbanir • Expira em 60s")

        success_embed = nextcord.Embed(
            title="🔓 Banimento Revogado",
            description=f"O banimento do usuário `{user_id}` foi removido com sucesso.",
            color=COLOR_SUCCESS,
            timestamp=nextcord.utils.utcnow()
        )
        success_embed.add_field(name="👤 Usuário ID", value=f"`{user_id}`", inline=True)
        success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        success_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"A revogação de banimento do usuário `{user_id}` foi cancelada.",
            color=COLOR_CANCEL
        )

        async def do_unban():
            try:
                await ctx.guild.unban(nextcord.Object(id=int(user_id)), reason=audit)
            except nextcord.NotFound:
                raise ModerationError("Esse usuário não está banido neste servidor.") from None
            return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=success_embed,
            cancel_embed=cancel_embed,
            on_confirm=do_unban,
            confirm_style=nextcord.ButtonStyle.success,
            force=force
        )

    @commands.command(cls=DualCommand, aliases=["expulsar"],
                      help="Expulsa um membro. Uso: r.kick @membro [motivo]. Requer Expulsar Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(kick_members=True)
    @commands.bot_has_guild_permissions(kick_members=True)
    async def kick(self, ctx, member: nextcord.Member, *, reason: str = None):
        check_target(ctx, member)
        clean_reason, force = extract_force_flag(reason)
        audit = audit_reason(ctx, clean_reason)
        display_reason = clean_reason or "Não informado"
        avatar = avatar_url(member)

        confirm_embed = nextcord.Embed(
            title="⚠️ Confirmação: Expulsar Membro",
            description=f"Tem certeza de que deseja expulsar {member_mention(member)} do servidor?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
        confirm_embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        if avatar:
            confirm_embed.set_thumbnail(url=avatar)
        confirm_embed.set_footer(text="Clique em Confirmar para expulsar • Expira em 60s")

        success_embed = nextcord.Embed(
            title="👢 Membro Expulso",
            description=f"O membro {member_mention(member)} foi expulso do servidor.",
            color=COLOR_DANGER,
            timestamp=nextcord.utils.utcnow()
        )
        success_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
        success_embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
        success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        success_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        if avatar:
            success_embed.set_thumbnail(url=avatar)
        success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"A expulsão de {member_mention(member)} foi cancelada pelo moderador.",
            color=COLOR_CANCEL
        )

        async def do_kick():
            await member.kick(reason=audit)
            return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=success_embed,
            cancel_embed=cancel_embed,
            on_confirm=do_kick,
            confirm_style=nextcord.ButtonStyle.danger,
            force=force
        )

    @commands.command(cls=DualCommand, aliases=["timeout", "silenciar"],
                      help="Aplica timeout: r.mute @membro 10m [motivo]. Aceita s/m/h/d, até 28d. Requer Moderar Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(moderate_members=True)
    @commands.bot_has_guild_permissions(moderate_members=True)
    async def mute(self, ctx, member: nextcord.Member, duration: str, *, reason: str = None):
        check_target(ctx, member, timeout=True)
        duration_delta = parse_duration(duration)
        clean_reason, force = extract_force_flag(reason)
        audit = audit_reason(ctx, clean_reason)
        display_reason = clean_reason or "Não informado"
        avatar = avatar_url(member)

        initial_until = nextcord.utils.utcnow() + duration_delta
        ts = int(initial_until.timestamp())

        confirm_embed = nextcord.Embed(
            title="⚠️ Confirmação: Silenciar Membro",
            description=f"Tem certeza de que deseja silenciar {member_mention(member)}?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
        confirm_embed.add_field(name="⏱️ Duração", value=f"`{duration}` (até <t:{ts}:F>)", inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        if avatar:
            confirm_embed.set_thumbnail(url=avatar)
        confirm_embed.set_footer(text="Clique em Confirmar para aplicar o timeout • Expira em 60s")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"O timeout de {member_mention(member)} foi cancelado pelo moderador.",
            color=COLOR_CANCEL
        )

        async def do_mute():
            exec_until = nextcord.utils.utcnow() + duration_delta
            exec_ts = int(exec_until.timestamp())
            await member.timeout(exec_until, reason=audit)
            success_embed = nextcord.Embed(
                title="🔇 Membro Silenciado",
                description=f"O membro {member_mention(member)} foi silenciado com sucesso.",
                color=COLOR_WARNING,
                timestamp=nextcord.utils.utcnow()
            )
            success_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
            success_embed.add_field(name="⏱️ Duração", value=f"`{duration}`", inline=True)
            success_embed.add_field(name="📅 Expira em", value=f"<t:{exec_ts}:F> (<t:{exec_ts}:R>)", inline=True)
            success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
            success_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
            if avatar:
                success_embed.set_thumbnail(url=avatar)
            success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")
            return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=None,
            cancel_embed=cancel_embed,
            on_confirm=do_mute,
            confirm_style=nextcord.ButtonStyle.danger,
            force=force
        )

    @commands.command(cls=DualCommand, aliases=["desmutar"],
                      help="Remove o timeout: r.unmute @membro [motivo]. Requer Moderar Membros.")
    @commands.guild_only()
    @commands.has_guild_permissions(moderate_members=True)
    @commands.bot_has_guild_permissions(moderate_members=True)
    async def unmute(self, ctx, member: nextcord.Member, *, reason: str = None):
        check_target(ctx, member)
        clean_reason, force = extract_force_flag(reason)
        audit = audit_reason(ctx, clean_reason)
        display_reason = clean_reason or "Não informado"
        avatar = avatar_url(member)

        confirm_embed = nextcord.Embed(
            title="⚠️ Confirmação: Remover Timeout",
            description=f"Tem certeza de que deseja remover o timeout de {member_mention(member)}?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        if avatar:
            confirm_embed.set_thumbnail(url=avatar)
        confirm_embed.set_footer(text="Clique em Confirmar para remover o timeout • Expira em 60s")

        success_embed = nextcord.Embed(
            title="🔊 Timeout Removido",
            description=f"O timeout do membro {member_mention(member)} foi removido com sucesso.",
            color=COLOR_SUCCESS,
            timestamp=nextcord.utils.utcnow()
        )
        success_embed.add_field(name="👤 Membro", value=f"{member_mention(member)} (`{member_name(member)}`)", inline=True)
        success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        success_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        if avatar:
            success_embed.set_thumbnail(url=avatar)
        success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"A remoção de timeout de {member_mention(member)} foi cancelada.",
            color=COLOR_CANCEL
        )

        async def do_unmute():
            await member.timeout(None, reason=audit)
            return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=success_embed,
            cancel_embed=cancel_embed,
            on_confirm=do_unmute,
            confirm_style=nextcord.ButtonStyle.success,
            force=force
        )

    async def change_lock(self, ctx, channel, reason, *, unlock, force=True):
        channel = await self.text_channel(ctx, channel, "manage_channels", "manage_roles")
        channel_mention = getattr(channel, "mention", f"<#{channel.id}>")
        clean_reason, has_force = extract_force_flag(reason)
        should_force = force or has_force
        audit = audit_reason(ctx, clean_reason)
        display_reason = clean_reason or "Não informado"

        previous = self.storage.channel_lock(ctx.guild.id, channel.id)
        if unlock and previous is None:
            raise ModerationError("Não há lock salvo pelo bot neste canal.")
        if not unlock and previous is not None:
            raise ModerationError("Este canal já tem um lock salvo. Use unlock para restaurar as permissões.")

        action_name = "Desbloquear" if unlock else "Bloquear"
        confirm_embed = nextcord.Embed(
            title=f"⚠️ Confirmação: {action_name} Canal",
            description=f"Tem certeza de que deseja {action_name.lower()} o canal {channel_mention}?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="💬 Canal", value=channel_mention, inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        confirm_embed.set_footer(text=f"Clique em Confirmar para {action_name.lower()} • Expira em 60s")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"A ação de {action_name.lower()} {channel_mention} foi cancelada.",
            color=COLOR_CANCEL
        )

        async def do_apply_lock():
            lock = self.channel_locks.setdefault(channel.id, asyncio.Lock())
            async with lock:
                fresh_channel = await ctx.guild.fetch_channel(channel.id)
                await self.text_channel(ctx, fresh_channel, "manage_channels", "manage_roles")
                current_prev = self.storage.channel_lock(ctx.guild.id, fresh_channel.id)
                if unlock and current_prev is None:
                    raise ModerationError("Não há lock salvo pelo bot neste canal.")
                if not unlock and current_prev is not None:
                    raise ModerationError("Este canal já tem um lock salvo. Use unlock para restaurar as permissões.")

                overwrite = fresh_channel.overwrites_for(ctx.guild.default_role)
                if unlock:
                    for flag in LOCK_FLAGS:
                        setattr(overwrite, flag, current_prev[flag])
                    await fresh_channel.set_permissions(ctx.guild.default_role,
                                                        overwrite=None if overwrite.is_empty() else overwrite,
                                                        reason=audit)
                    self.storage.delete_channel_lock(ctx.guild.id, fresh_channel.id)
                    success_embed = nextcord.Embed(
                        title="🔓 Canal Desbloqueado",
                        description=f"Permissões anteriores de {channel_mention} restauradas com sucesso.",
                        color=COLOR_SUCCESS,
                        timestamp=nextcord.utils.utcnow()
                    )
                else:
                    saved_prev = {flag: getattr(overwrite, flag) for flag in LOCK_FLAGS}
                    self.storage.save_channel_lock(ctx.guild.id, fresh_channel.id, saved_prev)
                    for flag in LOCK_FLAGS:
                        setattr(overwrite, flag, False)
                    try:
                        await fresh_channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=audit)
                    except (nextcord.Forbidden, nextcord.NotFound):
                        self.storage.delete_channel_lock(ctx.guild.id, fresh_channel.id)
                        raise
                    success_embed = nextcord.Embed(
                        title="🔒 Canal Bloqueado",
                        description=(f"{channel_mention} bloqueado para @everyone. "
                                     "Administradores e permissões explícitas de cargos/membros podem continuar permitindo mensagens."),
                        color=COLOR_DANGER,
                        timestamp=nextcord.utils.utcnow()
                    )
                success_embed.add_field(name="💬 Canal", value=channel_mention, inline=True)
                success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
                success_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
                success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")
                return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=None,
            cancel_embed=cancel_embed,
            on_confirm=do_apply_lock,
            confirm_style=nextcord.ButtonStyle.success if unlock else nextcord.ButtonStyle.danger,
            force=should_force
        )

    @commands.command(cls=DualCommand, aliases=["trancar"],
                      help="Bloqueia mensagens e tópicos para @everyone: r.lock [#canal] [motivo]. Requer Gerenciar Canais e Cargos.")
    @commands.guild_only()
    async def lock(self, ctx, channel: nextcord.TextChannel = None, *, reason: str = None):
        clean_reason, force = extract_force_flag(reason)
        await self.change_lock(ctx, channel, clean_reason, unlock=False, force=force)

    @commands.command(cls=DualCommand, aliases=["destrancar"],
                      help="Restaura as permissões anteriores ao lock: r.unlock [#canal] [motivo]. Requer Gerenciar Canais e Cargos.")
    @commands.guild_only()
    async def unlock(self, ctx, channel: nextcord.TextChannel = None, *, reason: str = None):
        clean_reason, force = extract_force_flag(reason)
        await self.change_lock(ctx, channel, clean_reason, unlock=True, force=force)

    @commands.command(cls=DualCommand, aliases=["limpar", "purge"],
                      help="Exclui de 1 a 100 mensagens anteriores ao comando: r.clear 10. Requer Gerenciar Mensagens e Ler Histórico.")
    @commands.guild_only()
    async def clear(self, ctx, amount: int):
        if not 1 <= amount <= 100:
            raise ModerationError("Escolha de 1 a 100 mensagens para excluir.")
        channel = await self.text_channel(ctx, None, "manage_messages", "read_message_history")
        boundary = ctx.interaction.created_at if getattr(ctx, "interaction", None) else ctx.message
        channel_mention = getattr(channel, "mention", f"<#{channel.id}>")

        confirm_embed = nextcord.Embed(
            title="⚠️ Confirmação: Limpar Mensagens",
            description=f"Tem certeza de que deseja excluir até **{amount}** mensagens em {channel_mention}?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="🗑️ Mensagens", value=f"**{amount}** mensagens", inline=True)
        confirm_embed.add_field(name="💬 Canal", value=channel_mention, inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.set_footer(text="Clique em Confirmar para excluir • Expira em 60s")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"A exclusão de mensagens em {channel_mention} foi cancelada.",
            color=COLOR_CANCEL
        )

        async def do_clear():
            deleted = await channel.purge(limit=amount, before=boundary)
            success_embed = nextcord.Embed(
                title="🧹 Mensagens Excluídas",
                description=f"**{len(deleted)}** mensagem(ns) foram excluídas com sucesso em {channel_mention}.",
                color=COLOR_SUCCESS,
                timestamp=nextcord.utils.utcnow()
            )
            success_embed.add_field(name="🗑️ Quantidade", value=f"{len(deleted)} mensagens", inline=True)
            success_embed.add_field(name="💬 Canal", value=channel_mention, inline=True)
            success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
            success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")
            return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=None,
            cancel_embed=cancel_embed,
            on_confirm=do_clear,
            confirm_style=nextcord.ButtonStyle.danger,
            force=False
        )

    @commands.command(cls=DualCommand, aliases=["modolento"],
                      help="Define o modo lento de 0 a 21600 segundos (0 desativa): r.slowmode 10 [#canal]. Requer Gerenciar Canais.")
    @commands.guild_only()
    async def slowmode(self, ctx, seconds: int, channel: nextcord.TextChannel = None, *, reason: str = None):
        if not 0 <= seconds <= 21600:
            raise ModerationError("Use de 0 a 21600 segundos; 0 desativa o modo lento.")
        channel = await self.text_channel(ctx, channel, "manage_channels")
        channel_mention = getattr(channel, "mention", f"<#{channel.id}>")
        clean_reason, force = extract_force_flag(reason)
        audit = audit_reason(ctx, clean_reason)
        display_reason = clean_reason or "Não informado"

        confirm_embed = nextcord.Embed(
            title="⚠️ Confirmação: Modo Lento",
            description=f"Deseja alterar o modo lento de {channel_mention}?",
            color=COLOR_CONFIRM,
            timestamp=nextcord.utils.utcnow()
        )
        confirm_embed.add_field(name="💬 Canal", value=channel_mention, inline=True)
        confirm_embed.add_field(name="⏱️ Intervalo", value=f"`{seconds}s`" if seconds > 0 else "`Desativado (0s)`", inline=True)
        confirm_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
        confirm_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
        confirm_embed.set_footer(text="Clique em Confirmar para alterar • Expira em 60s")

        cancel_embed = nextcord.Embed(
            title="❌ Ação Cancelada",
            description=f"A alteração do modo lento em {channel_mention} foi cancelada.",
            color=COLOR_CANCEL
        )

        async def do_slowmode():
            await channel.edit(slowmode_delay=seconds, reason=audit)
            success_embed = nextcord.Embed(
                title="⏳ Modo Lento Atualizado",
                description=(f"Modo lento de {channel_mention} definido para **{seconds}** segundo(s)."
                             if seconds > 0 else f"Modo lento de {channel_mention} foi **desativado**."),
                color=COLOR_INFO,
                timestamp=nextcord.utils.utcnow()
            )
            success_embed.add_field(name="💬 Canal", value=channel_mention, inline=True)
            success_embed.add_field(name="⏱️ Intervalo", value=f"{seconds} segundo(s)" if seconds > 0 else "Desativado", inline=True)
            success_embed.add_field(name="🛡️ Moderador", value=member_mention(ctx.author), inline=True)
            success_embed.add_field(name="📝 Motivo", value=display_reason, inline=False)
            success_embed.set_footer(text="Ação de moderação executada • Ralsei Moderation")
            return success_embed

        return await self.execute_with_confirmation(
            ctx,
            confirm_embed=confirm_embed,
            success_embed=None,
            cancel_embed=cancel_embed,
            on_confirm=do_slowmode,
            confirm_style=nextcord.ButtonStyle.primary,
            force=force
        )


def setup(bot):
    bot.add_cog(Moderation(bot))
