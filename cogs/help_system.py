"""Interactive categorized help menu and embeds for RalseiBot."""
import uuid

import nextcord
from nextcord.ext import commands

from cogs.command_support import slash_name

RALSEI_COLOR = 0x77E5BC

HELP_CATEGORIES = {
    "economia": {
        "label": "Economia",
        "emoji": "🪙",
        "description": "Trabalho, saldos, transferências e roubos de DarkMoney",
        "commands": ["balance", "daily", "pay", "work", "freelance", "rob"],
    },
    "jogos": {
        "label": "Jogos & Cassino",
        "emoji": "🎲",
        "description": "Blackjack, Minas, Dados, Caça-níqueis, Poker e Uno",
        "commands": ["blackjack", "dice", "mines", "poker", "six", "slots"],
    },
    "social": {
        "label": "Social & Casamento",
        "emoji": "💍",
        "description": "Perfil customizável, casamentos, ship e ranking global",
        "commands": [
            "profile",
            "profile color",
            "profile about",
            "profile background",
            "profile pet",
            "marry",
            "marriage",
            "divorce",
            "ship",
            "rich",
        ],
    },
    "roleplay": {
        "label": "Roleplay",
        "emoji": "🎭",
        "description": "Interações com GIFs animados de carinho e afeto",
        "commands": ["kiss", "hug", "pat"],
    },
    "missoes_musica": {
        "label": "Missões & Música",
        "emoji": "📜",
        "description": "Missões diárias com recompensas e música do dia",
        "commands": ["missions", "musica"],
    },
    "moderacao": {
        "label": "Moderação",
        "emoji": "🛡️",
        "description": "Punições, controle de canais e limpeza de mensagens",
        "commands": ["ban", "unban", "kick", "mute", "unmute", "lock", "unlock", "clear", "slowmode"],
    },
    "administracao": {
        "label": "Administração",
        "emoji": "⚙️",
        "description": "Painéis, quiz, tickets, confissões e economia de administradores",
        "commands": [
            "activity",
            "addbalance",
            "setbalance",
            "resetbalance",
            "confess",
            "quiz",
            "quizpanel",
            "quizoff",
            "ticket",
            "close",
            "send",
            "embedsend",
            "admmusica",
            "sync",
        ],
    },
    "geral": {
        "label": "Informações & Geral",
        "emoji": "ℹ️",
        "description": "Comandos gerais e utilidades do bot",
        "commands": ["help", "ping"],
    },
}


def build_home_embed(bot, user) -> nextcord.Embed:
    name = getattr(user, "display_name", None) or getattr(user, "name", "Viajante")
    embed = nextcord.Embed(
        title="✨ Central de Ajuda · Ralsei",
        color=RALSEI_COLOR,
        description=(
            f"Olá, **{name}**! Eu sou o **Ralsei**, o príncipe do Reino das Trevas! 💚\n"
            "Aqui você encontra todos os meus comandos organizados por categoria.\n\n"
            "📌 **Como usar meus comandos:**\n"
            "• **Slash:** Digite `/` e selecione o comando desejado.\n"
            "• **Prefixo:** Digite `r.<comando>` (ex.: `r.mines 100 5`).\n"
            "• **Ajuda específica:** Use `r.help <comando>` ou `/help command:<comando>`.\n\n"
            "📂 **Categorias disponíveis:**\n"
            "Selecione uma categoria no **menu abaixo** para ver os detalhes de cada comando!"
        ),
    )

    for key, cat in HELP_CATEGORIES.items():
        count = len(cat["commands"])
        embed.add_field(
            name=f"{cat['emoji']} {cat['label']}",
            value=f"{cat['description']}\n*{count} comando{'s' if count != 1 else ''}*",
            inline=True,
        )

    if bot.user and hasattr(bot.user, "display_avatar") and bot.user.display_avatar:
        try:
            embed.set_thumbnail(url=bot.user.display_avatar.url)
        except Exception:
            pass

    embed.set_footer(text=f"Solicitado por {name} • Escolha uma categoria no menu abaixo")
    return embed


def build_category_embed(bot, category_key: str, user) -> nextcord.Embed:
    cat = HELP_CATEGORIES.get(category_key)
    name = getattr(user, "display_name", None) or getattr(user, "name", "Viajante")
    if not cat:
        return build_home_embed(bot, user)

    embed = nextcord.Embed(
        title=f"{cat['emoji']} Comandos de {cat['label']}",
        color=RALSEI_COLOR,
        description=(
            f"*{cat['description']}*\n\n"
            "💡 *Dica: Use `r.help <comando>` ou `/help command:<comando>` para ver detalhes e opções completas.*"
        ),
    )

    for cmd_name in cat["commands"]:
        cmd = bot.get_command(cmd_name)
        if cmd is None:
            continue
        field_name = f"r.{cmd.qualified_name} · /{slash_name(cmd)}"
        doc = cmd.short_doc or "Veja a ajuda do comando."
        if cmd.aliases:
            parent = f"{cmd.parent.qualified_name} " if cmd.parent else ""
            aliases_str = ", ".join(f"`r.{parent}{alias}`" for alias in cmd.aliases)
            doc += f"\n↳ **Aliases:** {aliases_str}"
        embed.add_field(name=field_name, value=doc[:250], inline=False)

    embed.set_footer(text=f"Categoria {cat['label']} • Use o menu para alternar entre as categorias")
    return embed


def build_command_detail_embed(cmd: commands.Command, user) -> nextcord.Embed:
    name = getattr(user, "display_name", None) or getattr(user, "name", "Viajante")
    embed = nextcord.Embed(
        title=f"Ajuda: {cmd.qualified_name}",
        color=RALSEI_COLOR,
        description=cmd.help or "Sem descrição detalhada.",
    )
    sig = f" {cmd.signature}".rstrip()
    embed.add_field(name="Prefixo", value=f"`r.{cmd.qualified_name}{sig}`", inline=False)
    embed.add_field(name="Slash", value=f"`/{slash_name(cmd)}` — preencha as opções no Discord.", inline=False)
    if cmd.aliases:
        parent = f"{cmd.parent.qualified_name} " if cmd.parent else ""
        embed.add_field(
            name="Aliases do prefixo",
            value=", ".join(f"`r.{parent}{alias}`" for alias in cmd.aliases),
            inline=False,
        )
    embed.set_footer(text=f"Solicitado por {name} • Dica: Use r.help para voltar ao menu")
    return embed


def build_help_embed(bot, selection: str, user) -> nextcord.Embed:
    if selection == "home" or selection not in HELP_CATEGORIES:
        return build_home_embed(bot, user)
    return build_category_embed(bot, selection, user)


class HelpSelect(nextcord.ui.Select):
    def __init__(self, bot, author_id: int, current_category: str = "home"):
        self.bot = bot
        self.author_id = author_id
        options = [
            nextcord.SelectOption(
                label="Início",
                value="home",
                description="Visão geral e guia de uso",
                emoji="🏠",
                default=(current_category == "home"),
            )
        ]
        for key, cat in HELP_CATEGORIES.items():
            options.append(
                nextcord.SelectOption(
                    label=cat["label"],
                    value=key,
                    description=cat["description"][:100],
                    emoji=cat["emoji"],
                    default=(current_category == key),
                )
            )
        super().__init__(
            custom_id=f"help:category:{author_id}:{uuid.uuid4().hex}",
            placeholder="Escolha uma categoria para ver os comandos...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: nextcord.Interaction):
        selected = self.values[0]
        for opt in self.options:
            opt.default = (opt.value == selected)
        embed = build_help_embed(self.bot, selected, interaction.user)
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(nextcord.ui.View):
    def __init__(self, bot, author_id: int, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.message = None
        self.select = HelpSelect(bot, author_id, current_category="home")
        self.add_item(self.select)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Apenas quem pediu a ajuda pode usar este menu.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        self.select.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

