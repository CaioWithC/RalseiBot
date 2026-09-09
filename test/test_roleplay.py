"""Roleplay rotation and durable spouse-only affinity, without Discord login."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from db import Database, EconomyError
from roleplay import GIFS, Roleplay


class RoleplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.cog = Roleplay(None, self.db)
        self.ctx = SimpleNamespace(author=SimpleNamespace(id=1), send=AsyncMock())
        self.member = SimpleNamespace(id=2)

    async def asyncTearDown(self):
        self.db.engine.dispose()

    async def test_each_action_cycles_all_six_gifs_independently(self):
        for index in range(8):
            for action, verb in (("kiss", "beijou"), ("hug", "abraçou"), ("pat", "fez carinho em")):
                await self.cog.interact(self.ctx, self.member, action)
                embed = self.ctx.send.call_args.kwargs["embed"]
                self.assertEqual(embed.image.url, GIFS[action][index % 6])
                self.assertIn(f"<@1> {verb} <@2>", embed.description)
                self.assertNotIn("footer", embed.to_dict())
                self.assertFalse(embed.fields)
                self.assertIsNone(embed.title)

    async def test_concurrent_commands_take_different_gifs(self):
        await asyncio.gather(*(self.cog.interact(self.ctx, self.member, "kiss") for _ in range(6)))
        self.assertEqual([call.kwargs["embed"].image.url for call in self.ctx.send.call_args_list], list(GIFS["kiss"]))

    async def test_spouses_gain_actual_points_and_other_members_do_not(self):
        self.db.marry(2, 1)
        for points, action in enumerate(GIFS, start=1):
            with patch("roleplay.random.randint", return_value=points):
                await self.cog.interact(self.ctx, self.member, action)
            embed = self.ctx.send.call_args.kwargs["embed"]
            self.assertIn(f"ganhou {points} ponto", embed.footer.text)
        self.assertEqual(self.db.marriage(1)["affinity"], 6)
        await self.cog.interact(self.ctx, SimpleNamespace(id=3), "kiss")
        self.assertNotIn("footer", self.ctx.send.call_args.kwargs["embed"].to_dict())
        self.assertEqual(self.db.marriage(1)["affinity"], 6)

    async def test_self_target_rejected_without_consuming_gif(self):
        with self.assertRaises(EconomyError):
            await self.cog.interact(self.ctx, self.ctx.author, "kiss")
        self.ctx.send.assert_not_awaited()
        await self.cog.interact(self.ctx, self.member, "kiss")
        self.assertEqual(self.ctx.send.call_args.kwargs["embed"].image.url, GIFS["kiss"][0])


class AffinityStorageTests(unittest.TestCase):
    def test_concurrent_awards_survive_restart_and_existing_marriages_start_at_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + (Path(directory) / "test.db").as_posix()
            db = Database(url)
            try:
                db.marry(1, 2)
                # Simulate a database created before the affinity table existed.
                with db.engine.begin() as connection:
                    connection.exec_driver_sql("DROP TABLE marriage_affinity")
                db.engine.dispose()
                db = Database(url)
                self.assertEqual(db.marriage(2)["affinity"], 0)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    awards = list(pool.map(lambda _: db.add_marriage_affinity(2, 1, 3), range(12)))
                self.assertEqual(awards, [3] * 12)
                self.assertEqual(db.add_marriage_affinity(1, 3, 3), 0)
                db.engine.dispose()
                db = Database(url)
                self.assertEqual(db.marriage(1)["affinity"], 36)
                self.assertEqual(db.marriage(1), db.marriage(2))
            finally:
                db.engine.dispose()
