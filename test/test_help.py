"""Unit tests for the categorized interactive help system."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import nextcord
from nextcord.ext import commands

from cogs.help_system import (
    HELP_CATEGORIES,
    RALSEI_COLOR,
    HelpSelect,
    HelpView,
    build_category_embed,
    build_command_detail_embed,
    build_help_embed,
    build_home_embed,
)
from main import create_bot


class HelpSystemTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = create_bot()
        self.author = SimpleNamespace(id=12345, display_name="TestUser", name="TestUser")
        self.other_user = SimpleNamespace(id=67890, display_name="OtherUser", name="OtherUser")

    async def asyncTearDown(self):
        await self.bot.close()

    def test_all_bot_commands_are_present_in_help_categories(self):
        registered_commands = {cmd.qualified_name for cmd in self.bot.walk_commands()}
        categorized_commands = {cmd for cat in HELP_CATEGORIES.values() for cmd in cat["commands"]}

        missing = registered_commands - categorized_commands
        self.assertEqual(missing, set(), f"Commands missing from HELP_CATEGORIES: {missing}")

    def test_build_home_embed_structure_and_color(self):
        embed = build_home_embed(self.bot, self.author)
        self.assertEqual(embed.color.value, RALSEI_COLOR)
        self.assertIn("Central de Ajuda", embed.title)
        self.assertIn("TestUser", embed.description)
        self.assertIn("/help command:<comando>", embed.description)
        self.assertEqual(len(embed.fields), len(HELP_CATEGORIES))

    def test_build_category_embed_lists_commands(self):
        for cat_key, cat_data in HELP_CATEGORIES.items():
            embed = build_category_embed(self.bot, cat_key, self.author)
            self.assertEqual(embed.color.value, RALSEI_COLOR)
            self.assertIn(cat_data["label"], embed.title)
            self.assertGreater(len(embed.fields), 0)
            for field in embed.fields:
                self.assertTrue(field.name.startswith("r."))

    def test_build_category_embed_fallback_to_home_on_unknown(self):
        embed = build_category_embed(self.bot, "invalid_category", self.author)
        self.assertIn("Central de Ajuda", embed.title)

    def test_build_command_detail_embed(self):
        cmd = self.bot.get_command("mines")
        self.assertIsNotNone(cmd)
        embed = build_command_detail_embed(cmd, self.author)
        self.assertEqual(embed.color.value, RALSEI_COLOR)
        self.assertEqual(embed.title, "Ajuda: mines")
        field_names = [f.name for f in embed.fields]
        self.assertIn("Prefixo", field_names)
        self.assertIn("Slash", field_names)
        self.assertIn("Aliases do prefixo", field_names)

    async def test_help_view_and_select_initialization(self):
        view = HelpView(self.bot, self.author.id)
        self.assertEqual(len(view.children), 1)
        select = view.children[0]
        self.assertIsInstance(select, HelpSelect)
        self.assertEqual(len(select.options), len(HELP_CATEGORIES) + 1)
        self.assertEqual(select.options[0].value, "home")
        self.assertTrue(select.custom_id.startswith(f"help:category:{self.author.id}:"))
        payload = select.to_component_dict()
        self.assertIn("custom_id", payload)
        self.assertEqual(payload["custom_id"], select.custom_id)

    async def test_help_select_callback_edits_message(self):
        view = HelpView(self.bot, self.author.id)
        select = view.children[0]
        select._selected_values = ["economia"]

        interaction = SimpleNamespace(
            user=self.author,
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await select.callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        embed = interaction.response.edit_message.call_args.kwargs["embed"]
        self.assertIn("Economia", embed.title)
        field_names = [f.name for f in embed.fields]
        self.assertTrue(any("r.balance" in name for name in field_names))

    async def test_help_view_interaction_check_blocks_other_users(self):
        view = HelpView(self.bot, self.author.id)

        intruder = SimpleNamespace(
            user=self.other_user,
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        allowed = await view.interaction_check(intruder)
        self.assertFalse(allowed)
        intruder.response.send_message.assert_awaited_once()
        self.assertTrue(intruder.response.send_message.call_args.kwargs["ephemeral"])
        self.assertIn("Apenas quem pediu", intruder.response.send_message.call_args.args[0])

        owner = SimpleNamespace(user=self.author)
        self.assertTrue(await view.interaction_check(owner))

    async def test_help_view_on_timeout_disables_select(self):
        view = HelpView(self.bot, self.author.id)
        mock_msg = SimpleNamespace(edit=AsyncMock())
        view.message = mock_msg

        self.assertFalse(view.select.disabled)
        await view.on_timeout()
        self.assertTrue(view.select.disabled)
        mock_msg.edit.assert_awaited_once_with(view=view)


if __name__ == "__main__":
    unittest.main()
