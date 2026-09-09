"""Relationship persistence, mutual consent, concurrent clicks and ship images."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
from PIL import Image

from db import Database, EconomyError, database
from marriage import Relationships, marriage_embed, render_ship, read_avatar


def tearDownModule():
    database.engine.dispose()


def avatar(color):
    output = BytesIO()
    Image.new("RGB", (256, 256), color).save(output, "PNG")
    return output.getvalue()


class RelationshipStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "relationships.db").as_posix()
        self.db = Database(self.url)

    def tearDown(self):
        self.db.engine.dispose()
        self.directory.cleanup()

    def test_ship_score_is_random_once_symmetric_and_survives_restart(self):
        with patch("db.secrets.randbelow", return_value=37) as random:
            self.assertEqual(self.db.ship_score(1, 2), 37)
            self.assertEqual(self.db.ship_score(2, 1), 37)
            self.db.engine.dispose()
            self.db = Database(self.url)
            self.assertEqual(self.db.ship_score("1", "2"), 37)
            random.assert_called_once_with(101)
        with patch("db.secrets.randbelow", return_value=100):
            self.assertEqual(self.db.ship_score(1, 3), 100)
        with patch("db.secrets.randbelow", return_value=0):
            self.assertEqual(self.db.ship_score(2, 3), 0)

    def test_simultaneous_ships_create_one_score(self):
        with patch("db.secrets.randbelow", return_value=64) as random:
            with ThreadPoolExecutor(max_workers=4) as pool:
                scores = list(pool.map(lambda i: self.db.ship_score(1, 2) if i % 2 else self.db.ship_score(2, 1), range(8)))
        self.assertEqual(scores, [64] * 8)
        random.assert_called_once()

    def test_marriage_persists_date_and_is_visible_to_both_spouses(self):
        self.db.add_balance(1, 500)
        record = self.db.marry(2, 1, now=1800000000)
        self.db.engine.dispose()
        self.db = Database(self.url)
        self.assertEqual(self.db.marriage(1), record)
        self.assertEqual(self.db.marriage(2), record)
        self.assertEqual(record["married_at"], 1800000000)
        self.assertEqual(self.db.balance(1), 500)
        for first, second in ((2, 1), (1, 3), (3, 2)):
            with self.assertRaises(EconomyError):
                self.db.marry(first, second, now=1900000000)
        self.assertIsNone(self.db.marriage(3))
        self.assertEqual(self.db.marriage(1), record)

    def test_overlapping_simultaneous_marriages_cannot_give_a_user_two_spouses(self):
        def marry(pair):
            try:
                return self.db.marry(*pair)
            except EconomyError:
                return None
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(marry, ((1, 2), (2, 3), (4, 2))))
        winners = [record for record in results if record is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.db.marriage(2), winners[0])
        for user_id in (1, 3, 4):
            record = self.db.marriage(user_id)
            if str(user_id) in (winners[0]["first_id"], winners[0]["second_id"]):
                self.assertEqual(record, winners[0])
            else:
                self.assertIsNone(record)

    def test_self_pairs_are_rejected_without_creating_a_marriage(self):
        for method in (self.db.marry, self.db.ship_score):
            with self.assertRaises(EconomyError):
                method(1, "1")
        self.assertIsNone(self.db.marriage(1))


class ProposalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.cog = Relationships(None, self.db)
        self.first = SimpleNamespace(id=1, display_name="Caio", bot=False)
        self.second = SimpleNamespace(id=2, display_name="Kris", bot=False)
        self.message = SimpleNamespace(edit=AsyncMock())
        self.ctx = SimpleNamespace(author=self.first, send=AsyncMock(return_value=self.message))

    async def asyncTearDown(self):
        self.cog.cog_unload()
        self.db.engine.dispose()

    async def proposal(self):
        await self.cog.marry.callback(self.cog, self.ctx, self.second)
        return self.cog.proposals[1]

    def interaction(self, user_id):
        return SimpleNamespace(user=SimpleNamespace(id=user_id), message=self.message,
                               response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=Mock(return_value=True)),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def test_proposer_and_recipient_must_each_click_confirmation(self):
        view = await self.proposal()
        self.assertEqual(view.confirmed, set())
        self.assertIsNone(self.db.marriage(1))
        await view.confirm.callback(self.interaction(1))
        self.assertIsNone(self.db.marriage(1))
        repeated = self.interaction(1)
        await view.confirm.callback(repeated)
        repeated.followup.send.assert_awaited_once()
        self.assertEqual(view.confirmed, {1})
        with patch("db.time.time", return_value=1800000000):
            await view.confirm.callback(self.interaction(2))
        self.assertTrue(view.done)
        self.assertEqual(self.db.marriage(1)["married_at"], 1800000000)
        self.assertEqual(self.db.marriage(1), self.db.marriage(2))
        self.assertTrue(all(item.disabled for item in view.children))
        self.assertEqual(self.cog.proposals, {})
        await view.confirm.callback(self.interaction(2))
        self.assertEqual(self.db.marriage(1)["married_at"], 1800000000)

    async def test_simultaneous_confirmations_and_repeated_clicks_create_one_marriage(self):
        view = await self.proposal()
        with patch.object(self.db, "marry", wraps=self.db.marry) as marry:
            await asyncio.gather(*(view.confirm.callback(self.interaction(i)) for i in (2, 1, 2, 1)))
        marry.assert_called_once_with(1, 2)
        self.assertIsNotNone(self.db.marriage(1))

    async def test_outsiders_cannot_confirm_or_cancel(self):
        view = await self.proposal()
        for button in (view.confirm, view.decline):
            outsider = self.interaction(3)
            await button.callback(outsider)
            outsider.response.send_message.assert_awaited_once()
            self.assertTrue(outsider.response.send_message.call_args.kwargs["ephemeral"])
            outsider.response.defer.assert_not_awaited()
        self.assertFalse(view.done)
        self.assertEqual(view.confirmed, set())

    async def test_either_person_can_decline_after_one_confirmation(self):
        for user_id in (1, 2):
            view = await self.proposal()
            await view.confirm.callback(self.interaction(1))
            await view.decline.callback(self.interaction(user_id))
            self.assertTrue(view.done)
            self.assertIsNone(self.db.marriage(1))
            self.assertEqual(self.cog.proposals, {})
            await view.confirm.callback(self.interaction(2))
            self.assertIsNone(self.db.marriage(1))

    async def test_timeout_disables_buttons_and_releases_both_users(self):
        view = await self.proposal()
        await view.confirm.callback(self.interaction(2))
        await view.on_timeout()
        self.assertTrue(view.done)
        self.assertEqual(self.cog.proposals, {})
        self.assertIsNone(self.db.marriage(1))
        self.assertTrue(all(button.disabled for button in view.children))
        self.assertIn("expirou", view.result)
        self.message.edit.assert_awaited()
        self.assertIsNot(await self.proposal(), view)

    async def test_self_bots_existing_spouses_and_busy_people_are_rejected(self):
        for target in (self.first, SimpleNamespace(id=3, bot=True)):
            with self.assertRaises(EconomyError):
                await self.cog.marry.callback(self.cog, self.ctx, target)
        view = await self.proposal()
        with self.assertRaises(EconomyError):
            await self.proposal()
        self.ctx.author = SimpleNamespace(id=3, bot=False)
        with self.assertRaises(EconomyError):
            await self.cog.marry.callback(self.cog, self.ctx, self.second)
        await view.on_timeout()
        self.db.marry(1, 2)
        with self.assertRaises(EconomyError):
            await self.cog.marry.callback(self.cog, self.ctx, self.second)

    async def test_second_confirmation_rechecks_database_for_conflicting_marriage(self):
        view = await self.proposal()
        await view.confirm.callback(self.interaction(1))
        self.db.marry(2, 3)
        await view.confirm.callback(self.interaction(2))
        self.assertTrue(view.done)
        self.assertIsNone(self.db.marriage(1))
        self.assertIn("já está casada", view.result)
        self.assertEqual(self.cog.proposals, {})

    async def test_failed_initial_send_releases_pending_proposal(self):
        self.ctx.send.side_effect = RuntimeError("cannot send")
        with self.assertRaises(RuntimeError):
            await self.proposal()
        self.assertEqual(self.cog.proposals, {})
        self.assertIsNone(self.db.marriage(1))

    async def test_failed_message_edit_does_not_undo_a_confirmed_marriage(self):
        view = await self.proposal()
        await view.confirm.callback(self.interaction(1))
        error = nextcord.HTTPException(SimpleNamespace(status=500, reason="failed"), "cannot edit")
        self.message.edit.side_effect = error
        interaction = self.interaction(2)
        with self.assertRaises(nextcord.HTTPException):
            await view.confirm.callback(interaction)
        record = self.db.marriage(1)
        self.assertIsNotNone(record)
        with self.assertLogs("marriage", level="ERROR"):
            await view.on_error(error, view.confirm, interaction)
        self.assertEqual(self.db.marriage(1), record)
        interaction.followup.send.assert_awaited_once()

    async def test_unloading_cog_stops_unfinished_views(self):
        view = await self.proposal()
        self.cog.cog_unload()
        self.assertTrue(view.is_finished())
        self.assertEqual(self.cog.proposals, {})
        self.assertIsNone(self.db.marriage(1))


class ShipImageTests(unittest.IsolatedAsyncioTestCase):
    def test_card_displays_both_avatars_and_percentage_below_them(self):
        with render_ship("Caio", "Kris", 87, avatar("red"), avatar("blue")) as output:
            with Image.open(output) as image:
                self.assertEqual(image.size, (1000, 680))
                self.assertEqual(image.getpixel((270, 270)), (255, 0, 0))
                self.assertEqual(image.getpixel((730, 270)), (0, 0, 255))
                colors = image.crop((350, 450, 650, 545)).getcolors(28500)
                self.assertIn((242, 159, 181), {color for count, color in colors})

    def test_missing_invalid_avatars_long_names_and_extreme_scores_render(self):
        for score in (0, 100):
            with render_ship("Caio " * 60, "", score, None, b"not an image") as output:
                with Image.open(output) as image:
                    self.assertEqual(image.format, "PNG")
                    image.verify()

    async def test_avatar_download_timeout_uses_fallback(self):
        asset = SimpleNamespace(read=AsyncMock(side_effect=asyncio.TimeoutError))
        asset.with_size = lambda _: asset
        asset.with_static_format = lambda _: asset
        self.assertIsNone(await read_avatar(SimpleNamespace(display_avatar=asset)))

    def test_marriage_embed_includes_pair_wedding_date_and_relative_duration(self):
        embed = marriage_embed({"first_id": "1", "second_id": "2", "married_at": 1800000000})
        self.assertIn("<@1>", embed.description)
        self.assertIn("<@2>", embed.description)
        self.assertEqual(embed.fields[0].value, "<t:1800000000:F>")
        self.assertEqual(embed.fields[1].value, "<t:1800000000:R>")


if __name__ == "__main__":
    unittest.main()
