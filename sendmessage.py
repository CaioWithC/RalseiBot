import nextcord
import json
from nextcord.ext import commands

from command_support import DualCommand


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

class SendMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
