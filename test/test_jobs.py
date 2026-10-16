"""Comprehensive unit tests for job rules, schedules, experience, leveling, and database persistence."""
import asyncio
from datetime import datetime, timezone, timedelta
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
from db import Database, EconomyError
from cogs.job_rules import (
    DAILY_TIMEZONE, Job, WORK_JOBS, FREELANCE_JOBS, ALL_JOBS,
    get_available_jobs, find_job, calculate_level, get_level_info,
    format_progress_bar, get_shift_info, LEVELS
)
from cogs.economy import Economy, JobSelectView, build_job_menu_embed


class JobRulesTests(unittest.TestCase):
    def test_every_hour_has_sufficient_work_and_freelance_options(self):
        for hour in range(24):
            with self.subTest(hour=hour):
                work_jobs = get_available_jobs("work", hour)
                freelance_jobs = get_available_jobs("freelance", hour)
                self.assertGreaterEqual(len(work_jobs), 3, f"Hour {hour} has fewer than 3 work options")
                self.assertGreaterEqual(len(freelance_jobs), 3, f"Hour {hour} has fewer than 3 freelance options")

    def test_overnight_and_standard_hour_spans(self):
        # Caixa is 24h
        caixa = next(j for j in WORK_JOBS if j.id == "caixa")
        self.assertTrue(all(caixa.is_available(h) for h in range(24)))

        # Barman is 18 to 2
        barman = next(j for j in WORK_JOBS if j.id == "barman")
        self.assertTrue(barman.is_available(18))
        self.assertTrue(barman.is_available(23))
        self.assertTrue(barman.is_available(0))
        self.assertTrue(barman.is_available(1))
        self.assertFalse(barman.is_available(2))
        self.assertFalse(barman.is_available(12))

        # Barista is 6 to 14
        barista = next(j for j in WORK_JOBS if j.id == "barista")
        self.assertTrue(barista.is_available(6))
        self.assertTrue(barista.is_available(13))
        self.assertFalse(barista.is_available(14))
        self.assertFalse(barista.is_available(5))

    def test_find_job_by_id_and_title(self):
        self.assertEqual(find_job("work", "dev").id, "dev")
        self.assertEqual(find_job("work", "DEV").id, "dev")
        self.assertEqual(find_job("work", "software").id, "dev")
        self.assertEqual(find_job("freelance", "pizza").id, "pizza")
        self.assertEqual(find_job("freelance", "logotipo").id, "logo")
        self.assertIsNone(find_job("work", "inexistente"))
        self.assertIsNone(find_job("freelance", ""))

    def test_level_calculation_and_thresholds(self):
        self.assertEqual(calculate_level(0), 1)
        self.assertEqual(calculate_level(1), 1)
        self.assertEqual(calculate_level(2), 1)
        self.assertEqual(calculate_level(3), 2)
        self.assertEqual(calculate_level(7), 2)
        self.assertEqual(calculate_level(8), 3)
        self.assertEqual(calculate_level(14), 3)
        self.assertEqual(calculate_level(15), 4)
        self.assertEqual(calculate_level(24), 4)
        self.assertEqual(calculate_level(25), 5)
        self.assertEqual(calculate_level(100), 5)

    def test_level_info_and_bonuses(self):
        lvl, title, bonus, xp, next_thr, prev_thr = get_level_info(0)
        self.assertEqual(lvl, 1)
        self.assertEqual(title, "Iniciante")
        self.assertEqual(bonus, 0.0)
        self.assertEqual(next_thr, 3)

        lvl, title, bonus, xp, next_thr, prev_thr = get_level_info(5)
        self.assertEqual(lvl, 2)
        self.assertEqual(title, "Júnior")
        self.assertEqual(bonus, 0.15)
        self.assertEqual(next_thr, 8)

        lvl, title, bonus, xp, next_thr, prev_thr = get_level_info(30)
        self.assertEqual(lvl, 5)
        self.assertEqual(title, "Mestre")
        self.assertEqual(bonus, 1.00)
        self.assertIsNone(next_thr)

    def test_progress_bar_formatting(self):
        bar_lvl1 = format_progress_bar(0)
        self.assertIn("0/3 XP", bar_lvl1)
        bar_max = format_progress_bar(30)
        self.assertIn("Nível Máximo!", bar_max)

    def test_shift_info(self):
        self.assertEqual(get_shift_info(8)[0], "Manhã")
        self.assertEqual(get_shift_info(14)[0], "Tarde")
        self.assertEqual(get_shift_info(20)[0], "Noite")
        self.assertEqual(get_shift_info(3)[0], "Madrugada")


class JobDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database("sqlite:///:memory:")

    def tearDown(self):
        self.db.engine.dispose()

    def test_experience_starts_at_zero_and_level_one(self):
        xp, level = self.db.get_job_experience(123, "work", "dev")
        self.assertEqual(xp, 0)
        self.assertEqual(level, 1)

    def test_record_job_work_credits_balance_and_accumulates_xp(self):
        res1 = self.db.record_job_work(123, "work", "dev", 20000)
        self.assertEqual(res1["balance"], 20000)
        self.assertEqual(res1["new_xp"], 1)
        self.assertEqual(res1["new_level"], 1)
        self.assertFalse(res1["leveled_up"])

        res2 = self.db.record_job_work(123, "work", "dev", 20000)
        self.assertEqual(res2["new_xp"], 2)
        self.assertFalse(res2["leveled_up"])

        # 3rd work triggers Level 2!
        res3 = self.db.record_job_work(123, "work", "dev", 20000)
        self.assertEqual(res3["new_xp"], 3)
        self.assertEqual(res3["new_level"], 2)
        self.assertTrue(res3["leveled_up"])
        self.assertEqual(res3["balance"], 60000)

        # Check stats mapping
        stats = self.db.get_user_job_stats(123, "work")
        self.assertEqual(stats["dev"], (3, 2))

    def test_freelance_experience_is_isolated_from_work(self):
        self.db.record_job_work(123, "work", "pizza", 10000)
        self.db.record_job_work(123, "freelance", "pizza", 3000)

        work_xp, work_lvl = self.db.get_job_experience(123, "work", "pizza")
        free_xp, free_lvl = self.db.get_job_experience(123, "freelance", "pizza")

        self.assertEqual(work_xp, 1)
        self.assertEqual(free_xp, 1)


class JobInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.cog = Economy(None, storage=self.db)
        self.author = SimpleNamespace(id=1, mention="<@1>", display_name="Worker", bot=False)
        self.command = SimpleNamespace(reset_cooldown=Mock())
        self.ctx = SimpleNamespace(
            author=self.author,
            send=AsyncMock(),
            command=self.command,
            prefix="r.",
            invoked_with="work"
        )

    async def asyncTearDown(self):
        self.db.engine.dispose()

    async def test_menu_is_sent_when_no_job_arg_is_given(self):
        await Economy.work.callback(self.cog, self.ctx)
        self.ctx.send.assert_awaited_once()
        kwargs = self.ctx.send.call_args.kwargs
        embed = kwargs["embed"]
        view = kwargs["view"]

        self.assertIn("Mercado de Trabalho", embed.title)
        self.assertIsInstance(view, JobSelectView)
        self.assertEqual(view.author.id, self.author.id)
        self.assertGreaterEqual(len(view.select.options), 3)
        self.assertIsNotNone(view.select.custom_id)
        self.assertTrue(view.select.custom_id.startswith("job_select:work:"))
        self.assertEqual(view.select.to_component_dict()["custom_id"], view.select.custom_id)

    async def test_selecting_job_via_view_settles_reward_and_levels_up(self):
        await Economy.work.callback(self.cog, self.ctx)
        view = self.ctx.send.call_args.kwargs["view"]
        view.message = SimpleNamespace(edit=AsyncMock())

        interaction = SimpleNamespace(
            user=self.author,
            message=view.message,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock())
        )

        with patch("cogs.economy.random.randint", return_value=15000):
            # Select 24h job
            await view.choose_job(interaction, "caixa")

        view.message.edit.assert_awaited_once()
        result_embed = view.message.edit.call_args.kwargs["embed"]
        self.assertIn("Trabalho concluído", result_embed.title)
        self.assertIn("Operador de Caixa", result_embed.title)
        self.assertIn("15,000 D$", result_embed.description)
        self.assertEqual(self.db.balance(self.author.id), 15000)

        # Check XP gained
        xp, level = self.db.get_job_experience(self.author.id, "work", "caixa")
        self.assertEqual(xp, 1)
        self.assertEqual(level, 1)

    async def test_non_owner_cannot_interact_with_menu(self):
        await Economy.work.callback(self.cog, self.ctx)
        view = self.ctx.send.call_args.kwargs["view"]

        intruder = SimpleNamespace(
            user=SimpleNamespace(id=999),
            response=SimpleNamespace(send_message=AsyncMock())
        )
        allowed = await view.interaction_check(intruder)
        self.assertFalse(allowed)
        intruder.response.send_message.assert_awaited_once()
        self.assertTrue(intruder.response.send_message.call_args.kwargs["ephemeral"])

    async def test_view_timeout_resets_command_cooldown(self):
        await Economy.work.callback(self.cog, self.ctx)
        view = self.ctx.send.call_args.kwargs["view"]
        view.message = SimpleNamespace(edit=AsyncMock())

        await view.on_timeout()
        self.assertTrue(view.done)
        self.command.reset_cooldown.assert_called_once_with(self.ctx)
        view.message.edit.assert_awaited_once()
        self.assertIn("Tempo esgotado", view.message.edit.call_args.kwargs["embed"].title)

    async def test_direct_job_command_executes_immediately(self):
        with patch("cogs.economy.random.randint", return_value=12000):
            await Economy.work.callback(self.cog, self.ctx, vaga="caixa")

        self.ctx.send.assert_awaited_once()
        embed = self.ctx.send.call_args.kwargs["embed"]
        self.assertIn("Trabalho concluído", embed.title)
        self.assertIn("Operador de Caixa", embed.title)
        self.assertIn("12,000 D$", embed.description)
        self.assertEqual(self.db.balance(self.author.id), 12000)

    async def test_invalid_job_name_resets_cooldown_and_warns_user(self):
        await Economy.work.callback(self.cog, self.ctx, vaga="profissao_inexistente_xyz")
        self.command.reset_cooldown.assert_called_once_with(self.ctx)
        embed = self.ctx.send.call_args.kwargs["embed"]
        self.assertIn("Vaga não encontrada", embed.title)

    async def test_freelance_menu_and_direct_flow(self):
        self.ctx.invoked_with = "freelas"
        await Economy.freelance.callback(self.cog, self.ctx)
        view = self.ctx.send.call_args.kwargs["view"]
        self.assertEqual(view.category, "freelance")
        self.assertIn("Painel de Freelance", self.ctx.send.call_args.kwargs["embed"].title)

        self.ctx.send.reset_mock()
        with patch("cogs.economy.random.randint", return_value=3000):
            await Economy.freelance.callback(self.cog, self.ctx, vaga="redacao")
        embed = self.ctx.send.call_args.kwargs["embed"]
        self.assertIn("Freelance concluído", embed.title)
        self.assertIn("Redação de Artigos", embed.title)
        self.assertEqual(self.db.balance(self.author.id), 3000)


if __name__ == "__main__":
    unittest.main()
