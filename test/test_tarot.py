"""Unit tests for the Tarot cog, deck data, and table rendering."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import nextcord
from PIL import Image

from cogs.tarot import Tarot, TarotView
from cogs.tarot_data import draw_cards, format_card_reading, get_daily_card, get_daily_seed, load_deck
from cogs.tarot_render import render_single_card_table, render_three_card_table
from main import create_bot


class TarotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = create_bot()
        self.cog = self.bot.get_cog("Tarot")

    async def asyncTearDown(self):
        await self.bot.close()

    def test_deck_integrity(self):
        """Verify the 78 Rider-Waite-Smith cards and assets exist."""
        deck = load_deck()
        self.assertEqual(len(deck), 78)

        majors = [c for c in deck if c["arcana"] == "maior"]
        minors = [c for c in deck if c["arcana"] == "menor"]
        self.assertEqual(len(majors), 22)
        self.assertEqual(len(minors), 56)

        assets_dir = Path(__file__).resolve().parent.parent / "assets" / "tarot"
        for card in deck:
            self.assertTrue(card["name_pt"])
            self.assertTrue(card["name_en"])
            self.assertTrue(card["keywords_upright"])
            self.assertTrue(card["keywords_reversed"])
            self.assertTrue(card["div_mean_en"])

            img_path = assets_dir / card["image"]
            self.assertTrue(img_path.exists(), f"Image {card['image']} not found on disk")

    def test_draw_cards(self):
        """Test drawing cards and check absence of duplicates."""
        drawn = draw_cards(3)
        self.assertEqual(len(drawn), 3)
        ids = [c[0]["id"] for c in drawn]
        self.assertEqual(len(set(ids)), 3)

    def test_daily_card_determinism(self):
        """Verify daily card is consistent for the same user on the same day."""
        card1, rev1 = get_daily_card(12345678)
        card2, rev2 = get_daily_card(12345678)
        self.assertEqual(card1["id"], card2["id"])
        self.assertEqual(rev1, rev2)

    def test_render_single_card_table(self):
        """Verify rendering 1-card table produces valid PNG."""
        deck = load_deck()
        card = deck[0]

        # Upright
        bio_up = render_single_card_table(card, is_reversed=False, title="CARTA DO DIA")
        self.assertIsInstance(bio_up, BytesIO)
        img_up = Image.open(bio_up)
        self.assertEqual(img_up.format, "PNG")
        self.assertEqual(img_up.size, (760, 680))

        # Reversed
        bio_rev = render_single_card_table(card, is_reversed=True, title="CARTA DO DIA")
        img_rev = Image.open(bio_rev)
        self.assertEqual(img_rev.format, "PNG")
        self.assertEqual(img_rev.size, (760, 680))

    def test_render_three_card_table(self):
        """Verify rendering 3-card table produces valid widescreen PNG."""
        deck = load_deck()
        cards_info = [
            (deck[0], False, "Passado"),
            (deck[1], True, "Presente"),
            (deck[2], False, "Futuro"),
        ]
        bio = render_three_card_table(cards_info, question="Qual é o meu caminho?")
        self.assertIsInstance(bio, BytesIO)
        img = Image.open(bio)
        self.assertEqual(img.format, "PNG")
        self.assertEqual(img.size, (1100, 680))

    async def test_tarot_command_daily_flow(self):
        """Test calling r.tarot without arguments defaults to Carta do Dia."""
        user = SimpleNamespace(
            id=999888,
            name="Viajante",
            display_name="Viajante",
            display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
        )
        ctx = AsyncMock()
        ctx.author = user
        ctx.send = AsyncMock()

        await self.cog.tarot(ctx, pergunta=None)
        ctx.send.assert_awaited_once()
        kwargs = ctx.send.await_args.kwargs
        self.assertIn("embed", kwargs)
        self.assertIn("file", kwargs)
        self.assertIn("view", kwargs)

        embed = kwargs["embed"]
        self.assertEqual(embed.title, "🔮 Oráculo de Tarot · Carta do Dia")
        self.assertEqual(embed.image.url, "attachment://tarot_table.png")

    async def test_tarot_command_question_flow(self):
        """Test calling r.tarot with a question triggers 3-card spread."""
        user = SimpleNamespace(
            id=999888,
            name="Viajante",
            display_name="Viajante",
            display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
        )
        ctx = AsyncMock()
        ctx.author = user
        ctx.send = AsyncMock()

        question = "O que me aguarda nesta nova jornada?"
        await self.cog.tarot(ctx, pergunta=question)
        ctx.send.assert_awaited_once()
        kwargs = ctx.send.await_args.kwargs

        embed = kwargs["embed"]
        self.assertEqual(embed.title, "🔮 Oráculo de Tarot · Tiragem das Três Fases")
        self.assertIn(question, embed.description)
        self.assertEqual(len(embed.fields), 3)

    async def test_tarot_view_interaction_check(self):
        """Test TarotView permits author and blocks other users."""
        author = SimpleNamespace(id=1001, display_name="Autor")
        other = SimpleNamespace(id=1002, display_name="Outro")
        deck = load_deck()
        view = TarotView(self.cog, author, "daily", None, [(deck[0], False)])

        interaction_author = AsyncMock()
        interaction_author.user = author
        self.assertTrue(await view.interaction_check(interaction_author))

        interaction_other = AsyncMock()
        interaction_other.user = other
        interaction_other.response.send_message = AsyncMock()
        self.assertFalse(await view.interaction_check(interaction_other))
        interaction_other.response.send_message.assert_awaited_once()

    async def test_tarot_view_waite_details(self):
        """Test clicking waite details button sends an ephemeral embed with full texts."""
        author = SimpleNamespace(id=1001, display_name="Autor")
        deck = load_deck()
        card = deck[0]
        view = TarotView(self.cog, author, "daily", None, [(card, False)])

        interaction = AsyncMock()
        interaction.user = author
        interaction.response.send_message = AsyncMock()

        await view.waite_details.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertTrue(kwargs.get("ephemeral"))
        embed = kwargs.get("embed")
        self.assertIn("Significados Originais", embed.title)
        self.assertIn("A.E. Waite", embed.footer.text)

    async def test_tarot_slash_command(self):
        """Test slash command /tarot invocations via SlashCommands cog."""
        slash_cog = self.bot.get_cog("SlashCommands")
        self.assertIsNotNone(slash_cog)

        author = SimpleNamespace(
            id=1001,
            name="Viajante",
            display_name="Viajante",
            display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
            guild_permissions=SimpleNamespace(administrator=False),
        )
        interaction = AsyncMock()
        interaction.id = 555
        interaction.user = author
        interaction.guild = None
        interaction.channel = SimpleNamespace(id=123)
        interaction.created_at = datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc)
        interaction.response = SimpleNamespace(defer=AsyncMock(return_value=None))
        interaction.followup = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())))

        # Slash without question -> Daily card
        await slash_cog.tarot(interaction, pergunta=None)
        interaction.response.defer.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()
        kwargs = interaction.followup.send.await_args.kwargs
        embed = kwargs["embed"]
        self.assertEqual(embed.title, "🔮 Oráculo de Tarot · Carta do Dia")

    async def test_tarot_view_summarize_with_ai(self):
        """Test clicking Resumir calls AI cog and sends summary embed."""
        author = SimpleNamespace(id=1001, display_name="Viajante")
        deck = load_deck()
        cards_data = [(deck[0], False), (deck[1], True), (deck[2], False)]
        view = TarotView(self.cog, author, "three", "Qual meu conselho?", cards_data)

        ai_cog = self.bot.get_cog("AI")
        self.assertIsNotNone(ai_cog)
        ai_cog.explain_tarot = AsyncMock(return_value="As cartas indicam renovação e cuidado com ilusões.")

        interaction = AsyncMock()
        interaction.user = author
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()

        await view.summarize.callback(interaction)
        interaction.response.defer.assert_awaited_once()
        ai_cog.explain_tarot.assert_awaited_once_with(
            question="Qual meu conselho?",
            cards_data=cards_data,
            author_name="Viajante",
        )
        interaction.followup.send.assert_awaited_once()
        kwargs = interaction.followup.send.await_args.kwargs
        embed = kwargs["embed"]
        self.assertIn("Resumo da IA", embed.title)
        self.assertIn("As cartas indicam renovação", embed.description)
        self.assertIn("Qual meu conselho?", embed.description)

    async def test_ai_explain_tarot_generates_prompt(self):
        """Test AI cog's explain_tarot formats the prompt and calls generate_completion."""
        ai_cog = self.bot.get_cog("AI")
        self.assertIsNotNone(ai_cog)

        deck = load_deck()
        cards_data = [(deck[0], False)]

        ai_cog.generate_completion = AsyncMock(return_value=("Interpretação detalhada do Louco.", None))
        result = await ai_cog.explain_tarot(
            question=None,
            cards_data=cards_data,
            author_name="Caio",
        )
        self.assertEqual(result, "Interpretação detalhada do Louco.")
        ai_cog.generate_completion.assert_awaited_once()
        messages = ai_cog.generate_completion.await_args.args[0]
        self.assertEqual(len(messages), 2)
        self.assertIn("Ralsei", messages[0]["content"])
        self.assertIn(deck[0]["name_pt"], messages[1]["content"])


if __name__ == "__main__":
    unittest.main()

