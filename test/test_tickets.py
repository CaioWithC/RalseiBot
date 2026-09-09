"""Offline checks for ticket configuration and button behavior."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from db import Database
from tickets import TicketPanel, channel_slug


class HashableObject:
    def __init__(self, **values):
        self.__dict__.update(values)


class FakeCategory:
    def __init__(self, category_id=50):
        self.id = category_id
        self.name = "Support"
        self.overwrites = {}
        self.text_channels = []


class TicketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        url = "sqlite:///" + (Path(self.directory.name) / "test.db").as_posix()
        self.db = Database(url)

    async def asyncTearDown(self):
        self.db.engine.dispose()
        self.directory.cleanup()

    async def test_button_creates_private_numbered_channel_and_blocks_duplicate(self):
        category = FakeCategory()
        self.db.configure_tickets(10, category.id)
        user = HashableObject(id=20, display_name="João Teste", mention="<@20>")
        default_role = HashableObject()
        bot_member = HashableObject()
        channel = SimpleNamespace(mention="#joao-teste-1", send=AsyncMock(), topic="ticket-owner:20")
        guild = SimpleNamespace(
            id=10, default_role=default_role, me=bot_member,
            get_channel=lambda channel_id: category if channel_id == category.id else None,
            create_text_channel=AsyncMock(return_value=channel),
        )
        response = SimpleNamespace(defer=AsyncMock())
        interaction = SimpleNamespace(
            guild=guild, user=user, response=response,
            followup=SimpleNamespace(send=AsyncMock()),
        )
        view = TicketPanel(SimpleNamespace(), self.db)
        with patch("tickets.nextcord.CategoryChannel", FakeCategory):
            await view.open_ticket.callback(interaction)
            category.text_channels.append(channel)
            await view.open_ticket.callback(interaction)

        call = guild.create_text_channel.await_args
        kwargs = call.kwargs
        self.assertEqual(call.args[0], "joao-teste-1")
        self.assertEqual(kwargs["topic"], "ticket-owner:20")
        self.assertFalse(kwargs["overwrites"][default_role].view_channel)
        self.assertTrue(kwargs["overwrites"][user].view_channel)
        guild.create_text_channel.assert_awaited_once()
        self.assertIn("já tem", interaction.followup.send.await_args.args[0])

    def test_configuration_persists_and_numbers_are_monotonic(self):
        self.db.configure_tickets(10, 50)
        self.assertEqual(self.db.ticket_category(10), 50)
        self.assertEqual([self.db.next_ticket_number(10) for _ in range(3)], [1, 2, 3])
        self.db.configure_tickets(10, 60)
        self.assertEqual(self.db.ticket_category(10), 60)
        self.assertEqual(self.db.next_ticket_number(10), 4)
        self.assertEqual(channel_slug(" João  da Silva! "), "joao-da-silva")


if __name__ == "__main__":
    unittest.main()
