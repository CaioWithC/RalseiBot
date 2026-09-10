"""Mutual payment consent and settlement, without connecting to Discord."""
import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from nextcord.ext import commands

from db import Database, MAX_BALANCE
from economy import Economy, PaymentRequest


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.db.set_balance(1, 1000)
        self.sender = SimpleNamespace(id=1, display_name="Sender", bot=False)
        self.receiver = SimpleNamespace(id=2, display_name="Receiver", bot=False)
        self.view = PaymentRequest(self.sender, self.receiver, 100, storage=self.db)
        self.view.message = SimpleNamespace(edit=AsyncMock())

    async def asyncTearDown(self):
        self.view.stop()
        self.db.engine.dispose()

    def interaction(self, user_id):
        return SimpleNamespace(
            user=SimpleNamespace(id=user_id), message=self.view.message,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(),
                                     is_done=Mock(return_value=True)),
            followup=SimpleNamespace(send=AsyncMock()))

    def balances(self, sender=1000, receiver=0):
        self.assertEqual(self.db.balance(1), sender)
        self.assertEqual(self.db.balance(2), receiver)

    async def test_both_people_must_accept_and_duplicates_cannot_transfer_again(self):
        self.balances()
        await self.view.confirm.callback(self.interaction(2))
        self.balances()
        duplicate = self.interaction(2)
        await self.view.confirm.callback(duplicate)
        duplicate.followup.send.assert_awaited_once()
        self.balances()
        await asyncio.gather(*(self.view.confirm.callback(self.interaction(user_id))
                               for user_id in (1, 1, 2)))
        self.balances(900, 100)
        self.assertTrue(self.view.done)
        self.assertTrue(all(button.disabled for button in self.view.children))

    async def test_outsiders_cannot_accept_or_cancel(self):
        for button in (self.view.confirm, self.view.cancel):
            outsider = self.interaction(3)
            await button.callback(outsider)
            self.assertTrue(outsider.response.send_message.call_args.kwargs["ephemeral"])
        self.assertFalse(self.view.done)
        self.assertEqual(self.view.confirmed, set())
        self.balances()

    async def test_either_person_can_cancel_after_one_acceptance(self):
        for user_id in (1, 2):
            with self.subTest(user_id=user_id):
                view = PaymentRequest(self.sender, self.receiver, 100, storage=self.db)
                try:
                    await view.confirm.callback(self.interaction(1))
                    await view.cancel.callback(self.interaction(user_id))
                    await view.confirm.callback(self.interaction(2))
                    self.assertTrue(view.done)
                    self.assertIn("cancelou", view.content())
                    self.balances()
                finally:
                    view.stop()

    async def test_expiration_prevents_late_acceptance(self):
        await self.view.confirm.callback(self.interaction(1))
        await self.view.on_timeout()
        await self.view.confirm.callback(self.interaction(2))
        self.balances()
        self.assertIn("expirou", self.view.content())
        self.assertTrue(all(button.disabled for button in self.view.children))

    async def test_balance_is_rechecked_when_second_person_accepts(self):
        await self.view.confirm.callback(self.interaction(1))
        self.db.set_balance(1, 50)
        await self.view.confirm.callback(self.interaction(2))
        self.balances(50, 0)
        self.assertIn("saldo suficiente", self.view.content())
        self.assertTrue(self.view.done)

    async def test_receiver_overflow_does_not_debit_sender(self):
        self.db.set_balance(2, MAX_BALANCE)
        await self.view.confirm.callback(self.interaction(1))
        await self.view.confirm.callback(self.interaction(2))
        self.balances(1000, MAX_BALANCE)
        self.assertIn("limite", self.view.content())

    async def test_failed_receipt_does_not_allow_double_payment(self):
        await self.view.confirm.callback(self.interaction(1))
        error = RuntimeError("Message edit failed")
        self.view.message.edit.side_effect = error
        interaction = self.interaction(2)
        with self.assertRaises(RuntimeError):
            await self.view.confirm.callback(interaction)
        self.view.message.edit.side_effect = None
        with self.assertLogs("economy", level="ERROR"):
            await self.view.on_error(error, self.view.confirm, interaction)
        self.assertIn("transferiu", interaction.followup.send.call_args.args[0])
        await self.view.confirm.callback(self.interaction(1))
        await self.view.on_timeout()
        self.balances(900, 100)

    async def test_self_and_bot_payments_are_rejected_before_prompt(self):
        ctx = SimpleNamespace(author=self.sender, send=AsyncMock())
        with patch("economy.database", self.db):
            for member in (self.sender, SimpleNamespace(id=3, bot=True)):
                with self.assertRaises(commands.BadArgument):
                    await Economy.pay.callback(Economy(None), ctx, member, 100)
        ctx.send.assert_not_awaited()
        self.balances()


if __name__ == "__main__":
    unittest.main()
