"""Mission persistence, midnight rollover and atomic reward claims."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import unittest

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

from db import Database, EconomyError, MAX_BALANCE, next_daily_reset


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "missions.db").as_posix()
        self.db = Database(self.url)
        self.now = 1_800_000_000

    def tearDown(self):
        self.db.engine.dispose()
        self.directory.cleanup()

    def status(self, user=1, now=None):
        statuses, _ = self.db.mission_status(user, self.now if now is None else now)
        return {item["mission"].key: item for item in statuses}

    def test_progress_persists_and_rewards_are_claimed_once(self):
        self.db.daily(1, 100, now=self.now)
        self.db.job_reward(1, "work", 100, now=self.now)
        for _ in range(4):
            self.db.job_reward(1, "freelance", 100, now=self.now)
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.status()["freelance"]["progress"], 3)
        self.assertEqual(self.db.claim_missions(1, now=self.now), (15000, 15600))
        self.assertTrue(all(item["claimed"] for item in self.status().values()))
        with self.assertRaises(EconomyError):
            self.db.claim_missions(1, now=self.now)
        self.assertEqual(self.db.balance(1), 15600)
        self.assertTrue(all(item["progress"] == 0 for item in self.status(user=2).values()))

    def test_partial_claim_leaves_other_missions_available(self):
        self.db.daily(1, 100, now=self.now)
        self.db.job_reward(1, "freelance", 100, now=self.now)
        self.assertEqual(self.db.claim_missions(1, now=self.now)[0], 2500)
        for _ in range(2):
            self.db.job_reward(1, "freelance", 100, now=self.now)
        self.assertEqual(self.db.claim_missions(1, now=self.now)[0], 7500)

    def test_midnight_expires_unclaimed_rewards_and_restarts_progress(self):
        midnight = next_daily_reset(self.now)
        self.db.daily(1, 100, now=midnight - 1)
        self.db.job_reward(1, "freelance", 100, now=midnight - 1)
        with self.assertRaises(EconomyError):
            self.db.claim_missions(1, now=midnight)
        self.assertTrue(all(item["progress"] == 0 for item in self.status(now=midnight).values()))
        self.db.daily(1, 100, now=midnight)
        self.db.job_reward(1, "freelance", 100, now=midnight)
        self.assertEqual(self.status(now=midnight)["freelance"]["progress"], 1)
        self.assertEqual(self.db.claim_missions(1, now=midnight)[0], 2500)

    def test_failed_credit_preserves_progress_and_claimability(self):
        self.db.set_balance(1, MAX_BALANCE)
        with self.assertRaises(EconomyError):
            self.db.job_reward(1, "work", 100, now=self.now)
        self.assertEqual(self.status()["work"]["progress"], 0)
        self.db.set_balance(1, 0)
        self.db.daily(1, 100, now=self.now)
        self.db.set_balance(1, MAX_BALANCE)
        with self.assertRaises(EconomyError):
            self.db.claim_missions(1, now=self.now)
        self.assertFalse(self.status()["daily"]["claimed"])
        self.db.set_balance(1, 0)
        self.assertEqual(self.db.claim_missions(1, now=self.now), (2500, 2500))

    def test_admin_credits_and_invalid_jobs_do_not_advance_missions(self):
        self.db.add_balance(1, 100)
        self.db.set_balance(1, 200)
        with self.assertRaises(EconomyError):
            self.db.job_reward(1, "unknown", 100, now=self.now)
        self.assertTrue(all(item["progress"] == 0 for item in self.status().values()))

    def test_concurrent_claims_only_pay_once(self):
        self.db.daily(1, 100, now=self.now)

        def claim(_):
            try:
                return self.db.claim_missions(1, now=self.now)[0]
            except EconomyError:
                return 0

        with ThreadPoolExecutor(max_workers=4) as workers:
            self.assertEqual(sum(workers.map(claim, range(8))), 2500)
        self.assertEqual(self.db.balance(1), 2600)


if __name__ == "__main__":
    unittest.main()
