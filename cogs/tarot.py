"""Tarot reading cog with Rider-Waite-Smith cards and rendered table embeds."""
from io import BytesIO
from typing import List, Optional, Tuple

import nextcord
from nextcord.ext import commands

from cogs.command_support import DualCommand
from cogs.tarot_data import draw_cards, format_card_reading, get_daily_card
from cogs.tarot_render import render_single_card_table, render_three_card_table

RALSEI_COLOR = 0x77E5BC
STEVE_P_URL = "https://steve-p.org/divm/"


class TarotView(nextcord.ui.View):
    """Interactive view for re-rolling, switching modes, and reading Steve-P texts."""

    def __init__(
        self,
        cog: "Tarot",
        author: nextcord.User,
        mode: str,
        question: Optional[str],
        cards_data: List[Tuple[dict, bool]],
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.author = author
        self.mode = mode  # "daily" or "three"
        self.question = question
        self.cards_data = cards_data
        self.message: Optional[nextcord.Message] = None

        self._update_buttons()

    def _update_buttons(self):
        """Update switch button label depending on current mode."""
        if self.mode == "daily":
            self.switch_mode_button.label = "Tiragem de 3 Cartas"
            self.switch_mode_button.emoji = "🔮"
        else:
            self.switch_mode_button.label = "Carta do Dia"
            self.switch_mode_button.emoji = "☀️"

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "🔮 Essa mesa de leitura pertence a outro viajante. Use `r.tarot` ou `/tarot` para consultar seu próprio oráculo!",
                ephemeral=True,
            )
            return False
        return True

    @nextcord.ui.button(label="Nova Leitura", emoji="🔄", style=nextcord.ButtonStyle.primary, row=0)
    async def reroll(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        if self.mode == "daily":
            # For manual re-roll, draw a fresh random card
            cards = draw_cards(1)
            embed, image_file = self.cog.build_single_embed(
                self.author, cards[0][0], cards[0][1], is_fresh=True
            )
        else:
            cards = draw_cards(3)
            embed, image_file = self.cog.build_three_embed(
                self.author, cards, question=self.question
            )

        self.cards_data = cards
        self._update_buttons()
        await interaction.edit_original_message(embed=embed, file=image_file, view=self)

    @nextcord.ui.button(label="Alternar Modo", emoji="🔮", style=nextcord.ButtonStyle.secondary, row=0)
    async def switch_mode_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        if self.mode == "daily":
            self.mode = "three"
            cards = draw_cards(3)
            embed, image_file = self.cog.build_three_embed(
                self.author, cards, question=self.question
            )
        else:
            self.mode = "daily"
            card_dict, is_rev = get_daily_card(self.author.id)
            cards = [(card_dict, is_rev)]
            embed, image_file = self.cog.build_single_embed(
                self.author, card_dict, is_rev, is_fresh=False
            )

        self.cards_data = cards
        self._update_buttons()
        await interaction.edit_original_message(embed=embed, file=image_file, view=self)

    @nextcord.ui.button(label="Resumir", emoji="✨", style=nextcord.ButtonStyle.success, row=0)
    async def summarize(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Explain and summarize the drawn cards using Ralsei's AI from cogs/ai.py."""
        await interaction.response.defer()
        ai_cog = self.cog.bot.get_cog("AI")
        if not ai_cog:
            await interaction.followup.send(
                "O oráculo de inteligência artificial não está disponível no momento.",
                ephemeral=True,
            )
            return

        summary = await ai_cog.explain_tarot(
            question=self.question,
            cards_data=self.cards_data,
            author_name=self.author.display_name,
        )

        embed = nextcord.Embed(
            title="✨ Sabedoria do Oráculo · Resumo da IA",
            color=RALSEI_COLOR,
        )
        if self.question:
            desc = f"❓ **Pergunta:** “{self.question}”\n\n{summary}"
        else:
            desc = f"☀️ **Reflexão da Carta do Dia para {self.author.display_name}:**\n\n{summary}"

        if len(desc) > 4096:
            desc = desc[:4090] + "…"

        embed.description = desc
        embed.set_footer(
            text="Interpretação por IA (Ralsei) · Baralho Rider-Waite-Smith (1909)",
            icon_url=self.cog._bot_avatar_url(),
        )
        await interaction.followup.send(embed=embed)

    @nextcord.ui.button(label="Textos steve-p.org", emoji="📖", style=nextcord.ButtonStyle.secondary, row=0)
    async def waite_details(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        """Display full unabridged Waite text from steve-p.org in an ephemeral message."""
        embed = nextcord.Embed(
            title="📜 Significados Originais de A.E. Waite (1910)",
            description=(
                f"Textos divinatórios originais extraídos do oráculo [steve-p.org/divm]({STEVE_P_URL}) "
                "para as cartas sorteadas nesta leitura:"
            ),
            color=RALSEI_COLOR,
        )

        for card, is_rev in self.cards_data:
            orient = "Invertida (Reversed)" if is_rev else "Em pé (Upright)"
            name = f"{card['name_pt']} ({card['name_en']}) — {orient}"
            div_mean = card.get("div_mean_rev_en" if is_rev else "div_mean_en", "N/A")
            add_mean = card.get("add_mean_rev_en" if is_rev else "add_mean_en", "")

            value = f"**Divinatory Meaning:**\n*{div_mean}*"
            if add_mean:
                value += f"\n\n**Additional Meaning:**\n*{add_mean}*"

            if len(value) > 1024:
                value = value[:1020] + "…"

            embed.add_field(name=name, value=value, inline=False)

        embed.set_footer(text="Fonte: The Pictorial Key to the Tarot (A.E. Waite, 1910) · steve-p.org/divm")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except nextcord.HTTPException:
                pass


class Tarot(commands.Cog):
    """Tarot divination cog with Rider-Waite-Smith deck and graphical board tables."""

    def __init__(self, bot):
        self.bot = bot

    def _bot_avatar_url(self) -> Optional[str]:
        if self.bot.user and getattr(self.bot.user, "display_avatar", None):
            return self.bot.user.display_avatar.url
        return None

    def build_single_embed(
        self,
        author: nextcord.User,
        card: dict,
        is_reversed: bool,
        *,
        is_fresh: bool = False,
    ) -> Tuple[nextcord.Embed, nextcord.File]:
        """Build embed and rendered table image for a single card reading (Carta do Dia)."""
        reading = format_card_reading(card, is_reversed)
        subtitle = (
            f"Tiragem avulsa para {author.display_name}"
            if is_fresh
            else f"Guia e energia do dia para {author.display_name}"
        )

        image_bio = render_single_card_table(
            card,
            is_reversed=is_reversed,
            title="CARTA DO DIA" if not is_fresh else "LEITURA DE TAROT",
            subtitle=subtitle,
        )
        file = nextcord.File(fp=image_bio, filename="tarot_table.png")

        embed = nextcord.Embed(
            title="🔮 Oráculo de Tarot · Carta do Dia",
            color=RALSEI_COLOR,
            description=(
                f"✨ Olá, **{author.display_name}**! As cartas de **Rider-Waite-Smith** revelam "
                f"a energia e a sabedoria que regem a sua jornada hoje:"
            ),
        )

        card_title = f"{reading['symbol']} {reading['name_pt']} ({reading['name_en']}) — {reading['orientation']}"
        field_text = (
            f"🔑 **Palavras-chave:** {reading['keywords']}\n"
            f"📜 **Significado Tradicional (A.E. Waite):**\n"
            f"*{reading['waite_meaning']}*"
        )
        if reading["additional_meaning"]:
            field_text += f"\n\n💡 **Nuance Adicional:**\n*{reading['additional_meaning']}*"

        if len(field_text) > 1024:
            field_text = field_text[:1020] + "…"

        embed.add_field(name=card_title, value=field_text, inline=False)
        embed.set_image(url="attachment://tarot_table.png")
        embed.set_footer(
            text="Baralho Rider-Waite-Smith (1909) · steve-p.org/divm · Ralsei Bot",
            icon_url=self._bot_avatar_url(),
        )
        return embed, file

    def build_three_embed(
        self,
        author: nextcord.User,
        cards: List[Tuple[dict, bool]],
        question: Optional[str] = None,
    ) -> Tuple[nextcord.Embed, nextcord.File]:
        """Build embed and rendered table image for a 3-card spread reading."""
        positions = [
            ("Passado / Origem", "🕰️"),
            ("Presente / Desafio", "⚡"),
            ("Futuro / Conselho", "🌌"),
        ]

        table_info = [
            (cards[i][0], cards[i][1], positions[i][0]) for i in range(3)
        ]
        image_bio = render_three_card_table(
            table_info,
            title="LEITURA DE TAROT",
            question=question,
        )
        file = nextcord.File(fp=image_bio, filename="tarot_table.png")

        desc = (
            f"❓ **Pergunta:** “{question}”\n"
            f"As cartas de **Rider-Waite-Smith** foram consultadas para **{author.display_name}**:"
            if question
            else (
                f"✨ **{author.display_name}**, aqui está a sua tiragem das três fases do tempo:\n"
                "*Passado · Presente · Futuro*"
            )
        )

        embed = nextcord.Embed(
            title="🔮 Oráculo de Tarot · Tiragem das Três Fases",
            color=RALSEI_COLOR,
            description=desc,
        )

        for idx, (pos_name, pos_emoji) in enumerate(positions):
            card, is_rev = cards[idx]
            reading = format_card_reading(card, is_rev)
            f_title = f"{pos_emoji} {idx + 1}. {pos_name} — {reading['name_pt']} ({reading['orientation']})"
            f_val = (
                f"🔑 **Foco:** {reading['keywords']}\n"
                f"📜 *“{reading['waite_meaning']}”*"
            )
            if len(f_val) > 1024:
                f_val = f_val[:1020] + "…"
            embed.add_field(name=f_title, value=f_val, inline=False)

        embed.set_image(url="attachment://tarot_table.png")
        embed.set_footer(
            text="Baralho Rider-Waite-Smith (1909) · steve-p.org/divm · Ralsei Bot",
            icon_url=self._bot_avatar_url(),
        )
        return embed, file

    @commands.command(
        cls=DualCommand,
        name="tarot",
        aliases=["tarô", "taro"],
        help="Leitura de tarot: r.tarot [pergunta] para tiragem de 3 cartas, ou sem pergunta para a Carta do Dia.",
    )
    @commands.cooldown(1, 4, lambda message: message.author.id)
    async def tarot(self, ctx, *, pergunta: str = None):
        """Perform a tarot reading with Rider-Waite-Smith cards rendered on a table."""
        author = ctx.author

        # Check if user specifically requested Carta do Dia or left blank
        daily_triggers = ("dia", "diaria", "diária", "hoje", "daily", "carta do dia")
        is_daily = (pergunta is None) or (pergunta.strip().lower() in daily_triggers)

        if is_daily:
            card, is_rev = get_daily_card(author.id)
            cards_drawn = [(card, is_rev)]
            embed, file = self.build_single_embed(author, card, is_rev, is_fresh=False)
            mode = "daily"
            saved_question = None
        else:
            cards_drawn = draw_cards(3)
            embed, file = self.build_three_embed(author, cards_drawn, question=pergunta.strip())
            mode = "three"
            saved_question = pergunta.strip()

        view = TarotView(self, author, mode, saved_question, cards_drawn)
        msg = await ctx.send(embed=embed, file=file, view=view)
        view.message = msg


def setup(bot):
    bot.add_cog(Tarot(bot))
