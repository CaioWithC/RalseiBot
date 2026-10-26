"""Unit tests for the AI cog and r.ia command."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from main import create_bot


class AITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = create_bot()
        self.cog = self.bot.get_cog("AI")
        self.channel = SimpleNamespace(id=1001, typing=lambda: AsyncMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
        self.author = SimpleNamespace(id=2001, display_name="Kris", name="kris")

    async def asyncTearDown(self):
        await self.bot.close()

    def create_context(self, pergunta="Olá", is_interaction=False):
        ctx = SimpleNamespace(
            bot=self.bot,
            cog=self.cog,
            channel=self.channel,
            author=self.author,
            send=AsyncMock(),
            reply=AsyncMock(),
        )
        if is_interaction:
            ctx.interaction = SimpleNamespace()
        return ctx

    async def test_ia_command_responds_and_updates_memory(self):
        ctx = self.create_context("Como você está?")
        with patch.object(self.cog, "generate_completion", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = ("Eu estou muito bem, obrigado por perguntar! 🍰", None)
            await self.cog.ia.callback(self.cog, ctx, pergunta="Como você está?")

            mock_complete.assert_awaited_once()
            ctx.reply.assert_awaited_once_with("Eu estou muito bem, obrigado por perguntar! 🍰", mention_author=False)

            memory = self.cog.channel_memory[self.channel.id]
            self.assertEqual(len(memory), 2)
            self.assertEqual(memory[0]["role"], "user")
            self.assertIn("Como você está?", memory[0]["content"])
            self.assertEqual(memory[1]["role"], "assistant")
            self.assertEqual(memory[1]["content"], "Eu estou muito bem, obrigado por perguntar! 🍰")

    async def test_ia_command_without_question_warns_user(self):
        ctx = self.create_context("")
        with patch.object(self.cog, "generate_completion", new_callable=AsyncMock) as mock_complete:
            await self.cog.ia.callback(self.cog, ctx, pergunta=None)
            mock_complete.assert_not_awaited()
            ctx.send.assert_awaited_once()
            self.assertIn("faça uma pergunta", ctx.send.await_args.args[0])
            self.assertEqual(len(self.cog.channel_memory[self.channel.id]), 0)

    async def test_ia_command_splits_long_responses(self):
        ctx = self.create_context("Conte uma história longa")
        long_text = "Era uma vez no Reino das Trevas... " * 100  # ~3500 chars
        with patch.object(self.cog, "generate_completion", new_callable=AsyncMock) as mock_complete:
            mock_complete.return_value = (long_text, None)
            await self.cog.ia.callback(self.cog, ctx, pergunta="Conte uma história longa")

            ctx.reply.assert_awaited_once()
            ctx.send.assert_awaited_once()

    async def test_clearmemory_command_empties_channel_history(self):
        ctx = self.create_context()
        self.cog.channel_memory[self.channel.id] = [
            {"role": "user", "content": "Olá"},
            {"role": "assistant", "content": "Olá!"},
        ]
        await self.cog.clear_memory.callback(self.cog, ctx)
        self.assertNotIn(self.channel.id, self.cog.channel_memory)
        ctx.send.assert_awaited_once()
        self.assertIn("limpa", ctx.send.await_args.args[0])

    def test_on_message_listener_removed_from_ai(self):
        """Ensures that mentioning or replying to the bot no longer triggers AI on_message."""
        listeners = [listener[0] for listener in self.cog.get_listeners()]
        self.assertNotIn("on_message", listeners)


if __name__ == "__main__":
    unittest.main()

