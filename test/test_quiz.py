"""Offline quiz scheduling, exact-once prizes, persistence and moderation checks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
from sqlalchemy.orm import Session

from cogs.quiz import Quiz, QuizSuggestionModal
from cogs.quiz_rules import normalize_answer, suggestion_answers
from db import Database, EconomyError, MAX_BALANCE, QuizSuggestion


def forbidden():
    return nextcord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions")


class QuizTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "quiz.db").as_posix()
        self.db = Database(self.url)
        self.now = 10_000
        self.guild = SimpleNamespace(id=10, me=object(), default_role=object())
        self.chat = self.channel(50)
        self.review = self.channel(60, private=True)
        self.guild.get_channel = {50: self.chat, 60: self.review}.get
        self.bot = Mock()
        self.bot.get_guild.return_value = self.guild
        self.cog = Quiz(self.bot, self.db, clock=lambda: self.now, rng=random.Random(7))
        self.cog.register_views()
        self.db.configure_quiz(10, 50, 60, 1000, self.now + 1800)
        self.modals = []

    async def asyncTearDown(self):
        for modal in self.modals:
            modal.stop()
        self.cog.cog_unload()
        self.db.engine.dispose()
        self.directory.cleanup()

    def channel(self, channel_id, private=False):
        channel = Mock(spec=nextcord.TextChannel)
        channel.id, channel.guild, channel.mention = channel_id, self.guild, f"<#{channel_id}>"
        channel.send = AsyncMock(return_value=SimpleNamespace(id=100, edit=AsyncMock()))
        channel.permissions_for.side_effect = lambda member: nextcord.Permissions(
            view_channel=not (private and member is self.guild.default_role), send_messages=True, embed_links=True)
        return channel

    def message(self, text="conversa", user_id=20, message_id=200, **kwargs):
        values = dict(content=text, author=SimpleNamespace(id=user_id, bot=False, mention=f"<@{user_id}>"),
                      id=message_id, guild=self.guild, channel=self.chat, webhook_id=None)
        values.update(kwargs)
        return SimpleNamespace(**values)

    def interaction(self, user_id=20, moderator=False, interaction_id=123):
        return SimpleNamespace(id=interaction_id, guild=self.guild, channel_id=60,
            user=SimpleNamespace(id=user_id, guild_permissions=nextcord.Permissions(manage_messages=moderator)),
            message=SimpleNamespace(id=100, edit=AsyncMock()),
            _state=Mock(), response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), send_modal=AsyncMock(),
                                                    _responded=True, is_done=Mock(return_value=True)),
            followup=SimpleNamespace(send=AsyncMock()))

    async def activity(self, users=(20, 21, 20, 21, 20)):
        for user_id in users:
            await self.cog.on_message(self.message(user_id=user_id))

    def start_round(self, answers=None):
        self.now += 1800
        row = self.db.prepare_quiz_round(10, "Qual é a resposta?", answers or ["maçã"], self.now,
                                        self.now + 120, self.now + 1800)
        self.db.publish_quiz_round(row["id"], 100)
        return self.db.quiz_round(10)

    def modal(self):
        modal = QuizSuggestionModal(self.cog, 10, "60")
        self.modals.append(modal)
        return modal

    async def submit(self, interaction=None):
        interaction = interaction or self.interaction()
        modal = self.modal()
        interaction.data = {"components": [
            {"type": 1, "components": [{"type": 4, "custom_id": item.custom_id, "value": value}]}
            for item, value in ((modal.question, "Quantos lados tem um triângulo?"),
                                (modal.answer, "3"), (modal.aliases, "três\ntres"))]}
        await modal._scheduled_task(interaction)
        return interaction

    def test_normalization_preserves_meaning_and_validates_answers(self):
        self.assertEqual(normalize_answer("  MAÇÃ!  "), "maca")
        self.assertEqual(normalize_answer("São   Paulo"), "sao paulo")
        self.assertNotEqual(normalize_answer("-12"), normalize_answer("12"))
        self.assertNotEqual(normalize_answer("1.5"), normalize_answer("15"))
        for value in ("", "...", "a" * 101):
            with self.assertRaises(ValueError):
                suggestion_answers(value)
        with self.assertRaises(ValueError):
            suggestion_answers("x", "\n".join(str(i) for i in range(10)))

    async def test_schedule_requires_due_time_recent_activity_and_two_humans(self):
        await self.activity()
        await self.cog.tick_guild(10)
        self.chat.send.assert_not_awaited()
        self.now += 1800
        await self.cog.tick_guild(10)  # Earlier activity has expired.
        self.chat.send.assert_not_awaited()
        await self.activity((20,) * 5)
        await self.cog.tick_guild(10)
        self.chat.send.assert_not_awaited()
        await self.activity((21,))
        await asyncio.gather(self.cog.tick_guild(10), self.cog.tick_guild(10))
        self.chat.send.assert_awaited_once()
        row = self.db.quiz_round(10)
        self.assertEqual(row["expires_at"], self.now + 120)
        self.assertNotIn("answers", self.chat.send.call_args.kwargs["embed"].to_dict())
        self.assertTrue(1800 <= self.db.quiz_config(10)["next_at"] - self.now <= 3600)

    async def test_selection_excludes_three_latest_questions_and_releases_oldest(self):
        questions = [(f"Question {index}?", ["answer"]) for index in range(4)]
        asked = []
        with patch("cogs.quiz.SEED_QUESTIONS", questions), patch.object(
                self.cog.rng, "choice", side_effect=lambda choices: choices[0]):
            for _ in range(5):
                self.now = self.db.quiz_config(10)["next_at"]
                await self.activity()
                await self.cog.tick_guild(10)
                row = self.db.quiz_round(10)
                self.assertNotIn(row["question"], asked[-3:])
                asked.append(row["question"])
                self.db.expire_quiz_round(row["id"], row["expires_at"])
        self.assertEqual(asked, [question[0] for question in questions] + [questions[0][0]])

    async def test_bots_webhooks_commands_dms_and_other_channels_do_not_count_or_win(self):
        self.start_round()
        for message in (self.message("maçã", author=SimpleNamespace(bot=True)),
                        self.message("maçã", webhook_id=4), self.message("r.ping"),
                        self.message("maçã", guild=None), self.message("maçã", channel=self.review)):
            await self.cog.on_message(message)
        self.assertEqual(len(self.cog.activity[10]), 0)
        self.assertEqual(self.db.quiz_round(10)["status"], "active")

    async def test_only_first_correct_message_wins_and_receives_money(self):
        self.start_round()
        await self.cog.on_message(self.message("banana"))
        await self.cog.on_message(self.message("maçã", message_id=99))
        await asyncio.gather(self.cog.on_message(self.message(" MAÇA! ", user_id=20)),
                             self.cog.on_message(self.message("maçã", user_id=21)))
        self.assertEqual(self.db.balance(20), 1000)
        self.assertEqual(self.db.balance(21), 0)
        self.assertIsNone(self.db.quiz_round(10))
        self.chat.send.assert_awaited_once()

    async def test_payment_survives_failed_announcement_and_restart(self):
        row = self.start_round()
        self.chat.send.side_effect = forbidden()
        with self.assertLogs("cogs.quiz", level="WARNING"):
            await self.cog.on_message(self.message("maçã"))
        restarted = Database(self.url)
        try:
            self.assertEqual(restarted.balance(20), 1000)
            self.assertIsNone(restarted.answer_quiz(row["id"], 10, 50, 21, 201, "maçã", self.now))
        finally:
            restarted.engine.dispose()

    def test_database_serializes_competing_connections(self):
        row = self.start_round()
        def answer(user_id):
            return self.db.answer_quiz(row["id"], 10, 50, user_id, 200 + user_id, "maçã", self.now)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(answer, range(20, 28)))
        self.assertEqual(results.count(1000), 1)
        self.assertEqual(sum(self.db.balance(user) for user in range(20, 28)), 1000)

    def test_credit_failure_rolls_back_winner_and_prize(self):
        row = self.start_round()
        self.db.set_balance(20, MAX_BALANCE)
        with self.assertRaises(EconomyError):
            self.db.answer_quiz(row["id"], 10, 50, 20, 200, "maçã", self.now)
        self.assertEqual(self.db.quiz_round(10)["status"], "active")
        self.assertEqual(self.db.answer_quiz(row["id"], 10, 50, 21, 201, "maçã", self.now), 1000)

    async def test_timeout_rejects_late_answer_and_announces_only_once(self):
        self.start_round()
        self.now += 120
        await self.cog.on_message(self.message("maçã"))
        self.assertEqual(self.db.balance(20), 0)
        await self.cog.tick_guild(10)
        await self.cog.tick_guild(10)
        self.chat.send.assert_awaited_once()
        self.assertIn("Tempo esgotado", self.chat.send.call_args.args[0])

    async def test_failed_question_send_cancels_round_without_paying(self):
        self.now += 1800
        await self.activity()
        self.chat.send.side_effect = forbidden()
        with self.assertRaises(nextcord.Forbidden):
            await self.cog.tick_guild(10)
        self.assertIsNone(self.db.quiz_round(10))
        self.assertFalse(self.cog.recent_questions[10])
        self.assertGreater(self.db.quiz_config(10)["next_at"], self.now)

    async def test_active_round_and_schedule_survive_restart(self):
        row = self.start_round()
        restarted = Database(self.url)
        try:
            restarted.recover_quiz_rounds()
            self.assertEqual(restarted.quiz_round(10)["id"], row["id"])
            self.assertEqual(restarted.quiz_config(10)["next_at"], self.now + 1800)
            self.assertEqual(restarted.answer_quiz(row["id"], 10, 50, 20, 200, "maçã", self.now), 1000)
        finally:
            restarted.engine.dispose()

    async def test_real_modal_dispatch_sends_private_review_with_persistent_buttons(self):
        interaction = await self.submit()
        self.review.send.assert_awaited_once()
        self.chat.send.assert_not_awaited()
        payload = self.review.send.call_args.kwargs
        self.assertTrue(payload["view"].is_persistent())
        self.assertEqual(payload["allowed_mentions"].to_dict()["parse"], [])
        self.assertIn("ID: 20", payload["embed"].fields[1].value)
        self.assertEqual(self.db.approved_quiz_questions(10), [])
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertIn("Sugestão enviada", interaction.followup.send.call_args.args[0])

    async def test_moderator_only_and_duplicate_decisions_cannot_change_question_bank(self):
        await self.submit()
        unauthorized = self.interaction()
        await self.cog.review_view.approve.callback(unauthorized)
        unauthorized.response.send_message.assert_awaited_once()
        self.assertEqual(self.db.approved_quiz_questions(10), [])
        approved, rejected = self.interaction(moderator=True), self.interaction(moderator=True)
        await asyncio.gather(self.cog.review_view.approve.callback(approved),
                             self.cog.review_view.reject.callback(rejected))
        self.assertEqual(len(self.db.approved_quiz_questions(10)), 1)
        self.assertIn("já foi avaliada", rejected.followup.send.call_args.args[0])
        self.assertIsNone(approved.message.edit.call_args.kwargs["view"])
        self.assertEqual(self.db.approved_quiz_questions(11), [])

    async def test_rejected_question_stays_out_and_wrong_channel_cannot_review(self):
        await self.submit()
        interaction = self.interaction(moderator=True)
        interaction.channel_id = 50
        await self.cog.review_view.approve.callback(interaction)
        self.assertEqual(self.db.approved_quiz_questions(10), [])
        interaction.channel_id = 60
        await self.cog.review_view.reject.callback(interaction)
        self.assertEqual(self.db.approved_quiz_questions(10), [])
        self.assertIn("Recusada", interaction.followup.send.call_args.args[0])

    async def test_pending_suggestion_can_be_approved_after_restart(self):
        await self.submit()
        restarted = Database(self.url)
        try:
            row = restarted.review_quiz_suggestion(10, 60, 100, 30, True)
            self.assertEqual(row["moderator_id"], "30")
            self.assertEqual(restarted.approved_quiz_questions(10)[0][1], ["3", "três", "tres"])
        finally:
            restarted.engine.dispose()

    async def test_submission_limits_and_failure_do_not_approve_or_double_post(self):
        await self.submit()
        await self.submit()
        await self.submit(self.interaction(interaction_id=124))
        self.assertEqual(self.review.send.await_count, 1)
        self.now += 61
        self.review.send.side_effect = forbidden()
        interaction = await self.submit(self.interaction(interaction_id=125))
        self.assertIn("Não consegui", interaction.followup.send.call_args.args[0])
        with Session(self.db.engine) as session:
            self.assertEqual(session.get(QuizSuggestion, "125").status, "failed")

    def test_max_three_pending_and_interrupted_send_recovery(self):
        for index in range(3):
            self.db.submit_quiz_suggestion(index, 10, 20, "Qual é a resposta?", ["a"], 60, self.now + index * 61)
        with self.assertRaises(EconomyError):
            self.db.submit_quiz_suggestion(4, 10, 20, "Qual é a resposta?", ["a"], 60, self.now + 300)
        self.now += 1800
        self.db.prepare_quiz_round(10, "Pergunta?", ["a"], self.now, self.now + 120, self.now + 1800)
        self.db.recover_quiz_rounds()
        self.now += 1800
        self.assertIsNotNone(self.db.prepare_quiz_round(10, "Outra?", ["b"], self.now, self.now + 120, self.now + 1800))

    async def test_panel_disabled_and_stale_modal_rejected(self):
        modal = self.modal()
        self.db.disable_quiz(10)
        interaction = self.interaction()
        await self.cog.panel_view.suggest.callback(interaction)
        interaction.response.send_modal.assert_not_awaited()
        await modal.callback(interaction)
        self.review.send.assert_not_awaited()
        self.assertIn("configuração mudou", interaction.followup.send.call_args.args[0])

    async def test_disable_or_reconfigure_cancels_active_round(self):
        self.start_round()
        self.db.disable_quiz(10)
        await self.cog.on_message(self.message("maçã"))
        self.assertEqual(self.db.balance(20), 0)
        self.assertIsNone(self.db.quiz_round(10))
        self.db.configure_quiz(10, 50, 60, 2000, self.now + 1800)
        self.start_round()
        self.db.configure_quiz(10, 50, 60, 3000, self.now + 1800)
        self.assertIsNone(self.db.quiz_round(10))

    async def test_ready_registers_once_and_unload_stops_timer_and_views(self):
        self.bot.add_view.assert_has_calls([unittest.mock.call(self.cog.panel_view),
                                            unittest.mock.call(self.cog.review_view)])
        with patch.object(self.cog.ticker, "start") as start, patch.object(self.cog.ticker, "is_running", side_effect=[False, True]):
            await self.cog.on_ready()
            await self.cog.on_ready()
            start.assert_called_once()
        self.cog.cog_unload()
        self.assertTrue(self.cog.panel_view.is_finished())

    async def test_approved_suggestion_is_playable_with_accepted_alias(self):
        await self.submit()
        await self.cog.review_view.approve.callback(self.interaction(moderator=True))
        self.now += 1800
        await self.activity()
        with patch.object(self.cog.rng, "choice", side_effect=lambda questions: questions[-1]):
            await self.cog.tick_guild(10)
        self.assertEqual(self.db.quiz_round(10)["question"], "Quantos lados tem um triângulo?")
        await self.cog.on_message(self.message("TRÊS"))
        self.assertEqual(self.db.balance(20), 1000)

    async def test_public_review_channel_or_missing_permissions_prevent_setup(self):
        ctx = SimpleNamespace(guild=self.guild, send=AsyncMock())
        before = self.db.quiz_config(10)
        self.review.permissions_for.side_effect = lambda member: nextcord.Permissions(
            view_channel=True, send_messages=True, embed_links=True)
        await self.cog.quiz.callback(self.cog, ctx, self.chat, self.review, 2000)
        self.assertEqual(self.db.quiz_config(10), before)
        self.assertIn("negue Ver Canal", ctx.send.call_args.args[0])
        self.now += 1800
        await self.activity()
        self.chat.permissions_for.side_effect = lambda member: nextcord.Permissions.none()
        await self.cog.tick_guild(10)
        self.chat.send.assert_not_awaited()

    def test_wrong_guild_or_channel_cannot_claim_and_reward_must_be_valid(self):
        row = self.start_round()
        for guild_id, channel_id in ((11, 50), (10, 60)):
            self.assertIsNone(self.db.answer_quiz(row["id"], guild_id, channel_id, 20, 200, "maçã", self.now))
        for reward in (0, -1, 100001, True):
            with self.assertRaises(EconomyError):
                self.db.configure_quiz(10, 50, 60, reward, self.now + 1800)
        self.assertEqual(self.db.quiz_config(10)["reward"], 1000)


if __name__ == "__main__":
    unittest.main()
