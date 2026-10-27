import nextcord
import json
from nextcord.ext import commands

from cogs.command_support import DualCommand


OWNER_ID = 1241118323287261257


def embed_from_json(value):
    """Validate user JSON and turn it into a Discord embed."""
    try:
        data = json.loads(value)
    except json.JSONDecodeError as error:
        raise commands.BadArgument(
            f"JSON inválido na linha {error.lineno}, coluna {error.colno}."
        ) from error
    if not isinstance(data, dict):
        raise commands.BadArgument("O JSON precisa ser um objeto `{}`.")
    try:
        return nextcord.Embed.from_dict(data)
    except (TypeError, ValueError, AttributeError) as error:
        raise commands.BadArgument("O objeto JSON não contém um embed válido.") from error


def is_owner():
    """Check that restricts a command to the bot owner only."""
    async def predicate(ctx):
        if ctx.author.id != OWNER_ID:
            raise commands.CheckFailure("Apenas o dono do bot pode usar esse comando.")
        return True
    return commands.check(predicate)


class OwnerSayView(nextcord.ui.View):
    """View with selects for guild and channel, plus a modal to type the message."""

    def __init__(self, bot):
        super().__init__(timeout=120)
        self.bot = bot
        self.selected_guild = None
        self.selected_channel = None
        self._build_guild_select()

    def _build_guild_select(self):
        guilds = sorted(self.bot.guilds, key=lambda g: g.name.lower())[:25]
        options = [
            nextcord.SelectOption(label=g.name[:100], value=str(g.id), description=f"ID: {g.id}")
            for g in guilds
        ]
        self.guild_select = nextcord.ui.StringSelect(
            placeholder="Escolha o servidor...",
            options=options,
            custom_id="ownersay_guild",
        )
        self.guild_select.callback = self._on_guild_select
        self.add_item(self.guild_select)

    async def _on_guild_select(self, interaction: nextcord.Interaction):
        guild_id = int(self.guild_select.values[0])
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            await interaction.response.send_message("Servidor não encontrado.", ephemeral=True)
            return
        self.selected_guild = guild

        # Remove old items and rebuild with channel select
        self.clear_items()
        text_channels = [
            ch for ch in guild.text_channels
            if ch.permissions_for(guild.me).send_messages
        ][:25]
        if not text_channels:
            await interaction.response.send_message("Nenhum canal de texto acessível nesse servidor.", ephemeral=True)
            return

        options = [
            nextcord.SelectOption(
                label=f"#{ch.name}"[:100],
                value=str(ch.id),
                description=f"{ch.category.name if ch.category else 'Sem categoria'}"[:100],
            )
            for ch in text_channels
        ]
        self.channel_select = nextcord.ui.StringSelect(
            placeholder="Escolha o canal...",
            options=options,
            custom_id="ownersay_channel",
        )
        self.channel_select.callback = self._on_channel_select
        self.add_item(self.channel_select)

        await interaction.response.edit_message(
            content=f"🏠 Servidor: **{guild.name}**\nEscolha o canal:",
            view=self,
        )

    async def _on_channel_select(self, interaction: nextcord.Interaction):
        channel_id = int(self.channel_select.values[0])
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await interaction.response.send_message("Canal não encontrado.", ephemeral=True)
            return
        self.selected_channel = channel

        # Open modal to type the message
        await interaction.response.send_modal(OwnerSayModal(self))


class OwnerSayModal(nextcord.ui.Modal):
    """Modal for the owner to type the message to send."""

    def __init__(self, view: OwnerSayView):
        super().__init__(f"Enviar para #{view.selected_channel.name}")
        self.target_channel = view.selected_channel
        self.target_guild = view.selected_guild
        self.parent_view = view

        self.message_input = nextcord.ui.TextInput(
            label="Mensagem",
            placeholder="Digite a mensagem que o Ralsei enviará...",
            style=nextcord.TextInputStyle.paragraph,
            min_length=1,
            max_length=2000,
            required=True,
        )
        self.add_item(self.message_input)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            await self.target_channel.send(self.message_input.value)
            await interaction.response.send_message(
                f"✅ Mensagem enviada em **{self.target_guild.name}** → #{self.target_channel.name}!",
                ephemeral=True,
            )
        except nextcord.Forbidden:
            await interaction.response.send_message(
                "❌ Sem permissão para enviar mensagem nesse canal.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Erro: {e}",
                ephemeral=True,
            )
        self.parent_view.stop()


class SendMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        cls=DualCommand,
        name="ownersay",
        help="Dono: envia uma mensagem pelo Ralsei em qualquer servidor.",
    )
    @is_owner()
    async def owner_say(self, ctx, channel_id: str = None, *, message: str = None):
        if channel_id and message:
            # Direct mode: r.ownersay <channel_id> <message>
            try:
                channel = self.bot.get_channel(int(channel_id))
                if channel is None:
                    channel = await self.bot.fetch_channel(int(channel_id))
            except (ValueError, nextcord.NotFound, nextcord.Forbidden):
                await ctx.send("❌ Canal não encontrado ou inacessível.", ephemeral=True)
                return
            try:
                await channel.send(message)
                guild_name = channel.guild.name if hasattr(channel, "guild") and channel.guild else "DM"
                await ctx.send(
                    f"✅ Mensagem enviada em **{guild_name}** → #{channel.name}!",
                    ephemeral=True,
                )
            except nextcord.Forbidden:
                await ctx.send("❌ Sem permissão para enviar mensagem nesse canal.", ephemeral=True)
        else:
            # Interactive mode: show guild/channel selects + modal
            view = OwnerSayView(self.bot)
            is_interaction = getattr(ctx, "interaction", None) is not None
            kwargs = {"ephemeral": True} if is_interaction else {}
            await ctx.send("Escolha o servidor para enviar a mensagem:", view=view, **kwargs)

    @commands.command(
        cls=DualCommand,
        name="send",
        help="Apaga o comando do usuário e envia a mensagem pelo bot."
    )
    @commands.has_guild_permissions(administrator=True)
    @commands.guild_only()
    async def send_message(self, ctx, *, message: str):
        if getattr(ctx, "interaction", None) is None:
            await ctx.message.delete()
        await ctx.send(message)

    @commands.command(
        cls=DualCommand,
        name="embedsend",
        aliases=["sendembed"],
        help="Envia um embed através de JSON: r.embedsend {\"title\": \"Título\"}"
    )
    @commands.has_guild_permissions(administrator=True)
    @commands.guild_only()
    async def embed_send(self, ctx, *, json_data: str):
        embed = embed_from_json(json_data)
        if getattr(ctx, "interaction", None) is None:
            await ctx.message.delete()
        await ctx.send(embed=embed)

class EmbedJSONModal(nextcord.ui.Modal):
    def __init__(self):
        super().__init__("Criar Embed")

        self.json_input = nextcord.ui.TextInput(
            label="JSON",
            placeholder='{"title": "Título", "description": "Descrição"}',
            style=nextcord.TextInputStyle.paragraph,
            min_length=2,
            max_length=4000,
            required=True
        )

        self.add_item(self.json_input)

    async def callback(self, interaction: nextcord.Interaction):
        try:
            embed = embed_from_json(self.json_input.value)

            await interaction.response.defer(ephemeral=True)

            await interaction.channel.send(
                embed=embed
            )

            await interaction.followup.send(
                "✅ Embed enviado com sucesso!",
                ephemeral=True
            )

        except commands.BadArgument as error:
            await interaction.response.send_message(
                f"❌ {error}",
                ephemeral=True
            )


def setup(bot):
    bot.add_cog(SendMessage(bot))
