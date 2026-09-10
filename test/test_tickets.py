"""Offline checks for ticket configuration and button behavior."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord

from db import Database
from tickets import TicketPanel, Tickets, channel_slug


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

    def close_context(self, *, author_id=20, manage_channels=False):
        self.db.configure_tickets(10, 50)
        channel = Mock(spec=nextcord.TextChannel)
        channel.category_id = 50
        channel.topic = "ticket-owner:20"
        channel.delete = AsyncMock()
        channel.permissions_for.return_value = nextcord.Permissions(manage_channels=manage_channels)
        return SimpleNamespace(guild=SimpleNamespace(id=10), channel=channel,
                               author=SimpleNamespace(id=author_id), send=AsyncMock())

    async def test_owner_and_channel_staff_can_close_tickets(self):
        for author_id, manage_channels in ((20, False), (30, True)):
            with self.subTest(author_id=author_id):
                ctx = self.close_context(author_id=author_id, manage_channels=manage_channels)
                await Tickets.close.callback(Tickets(None, self.db), ctx)
                ctx.channel.delete.assert_awaited_once()
                self.assertIn(str(author_id), ctx.channel.delete.call_args.kwargs["reason"])
                self.assertIn("excluindo", ctx.send.call_args.args[0])

    async def test_other_members_cannot_close_ticket(self):
        ctx = self.close_context(author_id=30)
        await Tickets.close.callback(Tickets(None, self.db), ctx)
        ctx.channel.delete.assert_not_awaited()
        self.assertIn("Só o dono", ctx.send.call_args.args[0])

    async def test_normal_channels_and_wrong_categories_are_never_deleted(self):
        for topic, category_id in ((None, 50), ("general chat", 50), ("ticket-owner:20 extra", 50),
                                   ("ticket-owner:20", 99), ("ticket-owner:20", None)):
            with self.subTest(topic=topic, category_id=category_id):
                ctx = self.close_context(manage_channels=True)
                ctx.channel.topic = topic
                ctx.channel.category_id = category_id
                await Tickets.close.callback(Tickets(None, self.db), ctx)
                ctx.channel.delete.assert_not_awaited()

    async def test_threads_and_unconfigured_servers_cannot_be_closed(self):
        ctx = self.close_context()
        ctx.channel = Mock(spec=nextcord.Thread)
        ctx.channel.delete = AsyncMock()
        await Tickets.close.callback(Tickets(None, self.db), ctx)
        ctx.channel.delete.assert_not_awaited()
        ctx = self.close_context()
        ctx.guild.id = 99
        await Tickets.close.callback(Tickets(None, self.db), ctx)
        ctx.channel.delete.assert_not_awaited()

    async def test_delete_errors_are_reported_and_missing_channel_is_handled(self):
        for error_type, status, expected in ((nextcord.Forbidden, 403, "Gerenciar Canais"),
                                              (nextcord.HTTPException, 500, "Tente novamente"),
                                              (nextcord.NotFound, 404, None)):
            with self.subTest(status=status):
                ctx = self.close_context()
                ctx.channel.delete.side_effect = error_type(
                    SimpleNamespace(status=status, reason="error"), "error")
                await Tickets.close.callback(Tickets(None, self.db), ctx)
                if expected:
                    self.assertIn(expected, ctx.send.call_args.args[0])
                else:
                    ctx.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
