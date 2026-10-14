"""Tests for the Dice betting game (pure rules, UI views, and commands)."""
import asyncio
from datetime import datetime, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
from nextcord.ext import commands
from db import Database, EconomyError
from cogs.game_rules import (
    Dice, DICE_SIDES, DICE_MULTIPLIERS, parse_dice, validate_guess, RNG
)
from cogs.games import (
    DiceTypeButton, DiceNumberButton, DiceBackButton, DiceView, Games
)
from main import create_bot


class DiceRulesTests(unittest.TestCase):
    def test_dice_sides_and_increasing_multipliers(self):
        self.assertEqual(DICE_SIDES, (6, 8, 12, 20))
        # Larger dice have strictly higher multipliers
        multipliers = [DICE_MULTIPLIERS[s] for s in DICE_SIDES]
        self.assertEqual(multipliers, [6, 8, 12, 20])
        for i in range(len(multipliers) - 1):
            self.assertLess(multipliers[i], multipliers[i + 1])

    def test_parse_dice_accepts_valid_formats_and_rejects_others(self):
        self.assertIsNone(parse_dice(None))
        for input_val, expected in [
            ("d6", 6), ("D6", 6), ("6", 6), (6, 6),
            ("d8", 8), ("D8", 8), ("8", 8), (8, 8),
            ("d12", 12), ("D12", 12), ("12", 12), (12, 12),
            ("d20", 20), ("D20", 20), ("20", 20), (20, 20),
        ]:
            self.assertEqual(parse_dice(input_val), expected)

        for invalid in ["d10", "10", "d4", "4", "d100", "xyz", ""]:
            with self.assertRaises(EconomyError):
                parse_dice(invalid)

    def test_validate_guess_bounds(self):
        self.assertIsNone(validate_guess(None))
        self.assertEqual(validate_guess(5, 6), 5)
        self.assertEqual(validate_guess("12", 12), 12)
        self.assertEqual(validate_guess("20", 20), 20)

        for invalid_guess in [0, -1, 7]:
            with self.assertRaises(EconomyError):
                validate_guess(invalid_guess, 6)

        for invalid_guess in [0, 21]:
            with self.assertRaises(EconomyError):
                validate_guess(invalid_guess, 20)

        with self.assertRaises(EconomyError):
            validate_guess("abc", 6)

    def test_dice_game_win_and_loss_payouts(self):
        # Win on d6
        game_win_d6 = Dice(100, sides=6, guess=4, roll=4)
        self.assertEqual(game_win_d6.payout, 600)
        self.assertIn("Você acertou", game_win_d6.result)
        self.assertIn("6×", game_win_d6.result)

        # Loss on d6
        game_loss_d6 = Dice(100, sides=6, guess=4, roll=2)
        self.assertEqual(game_loss_d6.payout, 0)
        self.assertIn("Não foi dessa vez", game_loss_d6.result)

        # Win on d20
        game_win_d20 = Dice(50, sides=20, guess=17, roll=17)
        self.assertEqual(game_win_d20.payout, 1000)
        self.assertIn("20×", game_win_d20.result)

        # Loss on d20
        game_loss_d20 = Dice(50, sides=20, guess=17, roll=1)
        self.assertEqual(game_loss_d20.payout, 0)

    def test_dice_game_state_transitions(self):
        game = Dice(100)
        self.assertIsNone(game.sides)
        self.assertIsNone(game.guess)
        self.assertIsNone(game.payout)

        game.choose_sides(8)
        self.assertEqual(game.sides, 8)
        self.assertIn("d8 selecionado", game.result)

        game.reset_sides()
        self.assertIsNone(game.sides)

        game.choose_sides(12)
        game.play(12, 10, roll=10)
        self.assertEqual(game.payout, 1200)

        # Repeated play cannot change finished game
        game.play(12, 5, roll=5)
        self.assertEqual(game.payout, 1200)


class DiceUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = Database("sqlite:///:memory:")
        self.db.add_balance(1, 10_000)
        self.bet_id = self.db.reserve_bet(1, "dice", 100)

    def tearDown(self):
        self.db.engine.dispose()

    def interaction(self, user_id=1):
        response = SimpleNamespace(
            defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: False
        )
        msg = SimpleNamespace(edit=AsyncMock())
        return SimpleNamespace(
            user=SimpleNamespace(id=user_id),
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
            message=msg,
        )

    async def test_dice_view_interactive_selection_flow(self):
        game = Dice(100)
        view = DiceView(1, self.bet_id, game, storage=self.db)
        # Starts with dice selection (4 buttons: d6, d8, d12, d20)
        self.assertEqual(len(view.children), 4)
        self.assertTrue(all(isinstance(btn, DiceTypeButton) for btn in view.children))

        # Other user cannot click
        intruder = self.interaction(2)
        self.assertFalse(await view.interaction_check(intruder))

        # Owner clicks d6
        inter = self.interaction(1)
        await view.act(inter, lambda: view.select_sides(6))
        # Now shows 6 number buttons + 1 back button = 7
        self.assertEqual(len(view.children), 7)
        self.assertEqual(view.game.sides, 6)

        # Owner clicks back button
        await view.act(inter, view.back_to_dice_selection)
        self.assertEqual(len(view.children), 4)
        self.assertIsNone(view.game.sides)

        # Owner selects d20
        await view.act(inter, lambda: view.select_sides(20))
        # 20 number buttons + 1 back button = 21 items
        self.assertEqual(len(view.children), 21)

        # Pick number 15 with mock roll = 15 (win!)
        with patch.object(RNG, "randint", return_value=15):
            await view.act(inter, lambda: view.pick_number(15))

        self.assertTrue(view.done)
        self.assertEqual(view.game.payout, 2000)
        # Balance was 9900 + 2000 = 11900
        self.assertEqual(self.db.balance(1), 11900)
        self.assertTrue(all(btn.disabled for btn in view.children))

    async def test_dice_view_timeout_refunds_unsettled_game(self):
        game = Dice(100)
        view = DiceView(1, self.bet_id, game, storage=self.db)
        self.assertEqual(self.db.balance(1), 9900)
        await view.on_timeout()
        self.assertTrue(view.done)
        # Refunded 100
        self.assertEqual(self.db.balance(1), 10000)
        self.assertIn("devolvida", view.game.result)


class DiceCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.db.add_balance(1, 10_000)
        self.bot = create_bot()
        self.bot._connection.user = SimpleNamespace(id=999)
        self.bot.get_cog("Games").storage = self.db
        self.author = SimpleNamespace(id=1, display_name="Player 1", mention="<@1>", bot=False, guild_permissions=nextcord.Permissions.all())

    async def asyncTearDown(self):
        await self.bot.close()
        self.db.engine.dispose()

    async def prefix_context(self, content):
        message = SimpleNamespace(
            content=content, author=self.author, guild=None,
            channel=SimpleNamespace(id=123), attachments=[], edited_at=None,
            created_at=datetime.fromtimestamp(1_800_000_000, timezone.utc),
            _state=self.bot._connection,
        )
        ctx = await self.bot.get_context(message)
        ctx.send = AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))
        return ctx

    async def test_direct_prefix_command_rolls_and_pays(self):
        ctx = await self.prefix_context("r.dice 100 d6 3")
        with patch.object(RNG, "randint", return_value=3):
            await ctx.command.invoke(ctx)

        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        self.assertIn("Você acertou", embed.description)
        self.assertEqual(self.db.balance(1), 10_500)

    async def test_alias_dado_works(self):
        ctx = await self.prefix_context("r.dado 100 d8 5")
        with patch.object(RNG, "randint", return_value=1):
            await ctx.command.invoke(ctx)

        ctx.send.assert_awaited_once()
        embed = ctx.send.call_args.kwargs["embed"]
        self.assertIn("Não foi dessa vez", embed.description)
        self.assertEqual(self.db.balance(1), 9900)

    async def test_interactive_command_starts_view(self):
        ctx = await self.prefix_context("r.dice 100")
        await ctx.command.invoke(ctx)
        ctx.send.assert_awaited_once()
        view = ctx.send.call_args.kwargs["view"]
        self.assertEqual(type(view).__name__, "DiceView")
        self.assertFalse(view.done)
        await view.on_timeout()
        self.assertEqual(self.db.balance(1), 10_000)

    async def test_invalid_dice_raises_economy_error_without_spending(self):
        ctx = await self.prefix_context("r.dice 100 d10 5")
        with self.assertRaises(commands.CommandInvokeError) as caught:
            await ctx.command.invoke(ctx)
        self.assertIsInstance(caught.exception.original, EconomyError)
        self.assertEqual(self.db.balance(1), 10_000)

    async def test_slash_command_dice_rolls_and_pays(self):
        cog = self.bot.get_cog("SlashCommands")
        self.assertIsNotNone(cog)
        inter = SimpleNamespace(
            id=123, user=self.author, client=self.bot,
            created_at=datetime.fromtimestamp(1_800_000_000, timezone.utc),
            channel=SimpleNamespace(id=123, permissions_for=lambda m: m.guild_permissions),
            guild=None,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: False),
            data={"options": []},
            application_command=SimpleNamespace(name="dice", qualified_name="dice"),
            followup=SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))),
        )
        with patch.object(RNG, "randint", return_value=5):
            await cog.dice(inter, amount="100", dice="d8", number=5)

        inter.followup.send.assert_awaited_once()
        embed = inter.followup.send.call_args.kwargs["embed"]
        self.assertIn("Você acertou", embed.description)
        # 100 * 8 = 800 payout -> balance 10_000 - 100 + 800 = 10_700
        self.assertEqual(self.db.balance(1), 10_700)



if __name__ == "__main__":
    unittest.main()
