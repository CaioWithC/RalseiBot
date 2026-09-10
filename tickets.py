"""Persistent private ticket panels, channel creation and closing."""
import asyncio
import re
import unicodedata

import nextcord
from nextcord.ext import commands

from command_support import DualCommand
from db import EconomyError, database

TICKET_BUTTON_ID = "ralseibot:open-ticket"


def channel_slug(name):
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or "usuario")[:70]


class TicketPanel(nextcord.ui.View):
    def __init__(self, bot, storage=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.locks = {}

    def lock_for(self, guild_id, user_id):
        return self.locks.setdefault((guild_id, user_id), asyncio.Lock())

    @nextcord.ui.button(label="Abrir ticket", emoji="🎫", style=nextcord.ButtonStyle.green,
                        custom_id=TICKET_BUTTON_ID)
    async def open_ticket(self, button, interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Use este botão em um servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock_for(interaction.guild.id, interaction.user.id):
            category_id = self.storage.ticket_category(interaction.guild.id)
            category = interaction.guild.get_channel(category_id) if category_id else None
            if not isinstance(category, nextcord.CategoryChannel):
                await interaction.followup.send(
                    "A categoria de tickets não está configurada ou foi removida. Avise um administrador.",
                    ephemeral=True,
                )
                return
            owner_topic = f"ticket-owner:{interaction.user.id}"
            existing = next((channel for channel in category.text_channels
                             if channel.topic == owner_topic), None)
            if existing is not None:
                await interaction.followup.send(
                    f"Você já tem um ticket aberto: {existing.mention}", ephemeral=True
                )
                return
            number = self.storage.next_ticket_number(interaction.guild.id)
            overwrites = dict(category.overwrites)
            overwrites[interaction.guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
            overwrites[interaction.user] = nextcord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            )
            if interaction.guild.me is not None:
                overwrites[interaction.guild.me] = nextcord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_channels=True
                )
            try:
                channel = await interaction.guild.create_text_channel(
                    f"{channel_slug(interaction.user.display_name)}-{number}",
                    category=category,
                    overwrites=overwrites,
                    topic=owner_topic,
                    reason=f"Ticket #{number} aberto por {interaction.user} ({interaction.user.id})",
                )
                await channel.send(
                    f"{interaction.user.mention}, seu ticket foi aberto. Descreva aqui como podemos ajudar.\n"
                    "Use `r.close` ou `/close` para fechar o ticket e excluir este canal."
                )
            except nextcord.HTTPException:
                await interaction.followup.send(
                    "Não consegui criar o ticket. Verifique minhas permissões na categoria.", ephemeral=True
                )
                return
            await interaction.followup.send(f"Ticket criado: {channel.mention}", ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.persistent_view = None

    @commands.Cog.listener()
    async def on_ready(self):
        if self.persistent_view is None:
            self.persistent_view = TicketPanel(self.bot, self.storage)
            self.bot.add_view(self.persistent_view)

    @commands.command(cls=DualCommand, name="ticket",
                      help="Administrador: escolhe a categoria e publica o painel de tickets.")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def ticket(self, ctx, category: nextcord.CategoryChannel):
        self.storage.configure_tickets(ctx.guild.id, category.id)
        embed = nextcord.Embed(
            title="🎫 Atendimento",
            description="Clique no botão abaixo para abrir um ticket privado com a equipe.",
            color=0x77E5BC,
        )
        embed.set_footer(text=f"Os tickets serão criados em {category.name}.")
        await ctx.send(embed=embed, view=TicketPanel(self.bot, self.storage))

    @commands.command(cls=DualCommand, name="close", aliases=["fechar", "closeticket"],
                      help="Fecha o ticket atual e exclui seu canal. Somente o dono ou quem pode gerenciar canais.")
    @commands.guild_only()
    async def close(self, ctx):
        channel = ctx.channel
        category_id = self.storage.ticket_category(ctx.guild.id)
        if (not isinstance(channel, nextcord.TextChannel)
                or category_id is None or channel.category_id != category_id):
            await ctx.send("Use este comando dentro de um ticket na categoria configurada.")
            return
        owner = re.fullmatch(r"ticket-owner:([0-9]+)", channel.topic or "")
        if owner is None:
            await ctx.send("Este canal não é um ticket.")
            return
        if (ctx.author.id != int(owner[1])
                and not channel.permissions_for(ctx.author).manage_channels):
            await ctx.send("Só o dono do ticket ou quem tem permissão de Gerenciar Canais pode fechá-lo.")
            return
        await ctx.send("Fechando o ticket e excluindo este canal...")
        try:
            await channel.delete(reason=f"Ticket fechado por {ctx.author} ({ctx.author.id})")
        except nextcord.NotFound:
            # Another close request may have already deleted the channel.
            return
        except nextcord.Forbidden:
            await ctx.send("Não consegui fechar o ticket. Preciso da permissão de Gerenciar Canais.")
        except nextcord.HTTPException:
            await ctx.send("Não consegui fechar o ticket. Tente novamente em instantes.")


def setup(bot):
    bot.add_cog(Tickets(bot))
