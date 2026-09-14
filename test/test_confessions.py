"""Offline confession modal, upload, attribution and failure-path checks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
from nextcord.ext import commands
from PIL import Image
from sqlalchemy.orm import Session

from cogs.confessions import ConfessionModal, ConfessionPanel, Confessions, MAX_IMAGE_BYTES
from db import Confession, Database, EconomyError


def image_bytes(format="PNG"):
    stream = BytesIO()
    frames = [Image.new("RGB", (12, 12), color) for color in ("red", "blue")]
    frames[0].save(stream, format=format, **(
        {"save_all": True, "append_images": frames[1:], "duration": 100, "loop": 0}
        if format == "GIF" else {}))
    return stream.getvalue()


def http_error():
    return nextcord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions")


class ConfessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "sqlite:///" + (Path(self.directory.name) / "test.db").as_posix()
        self.db = Database(self.url)
        self.bot = Mock()
        self.bot.can_run = AsyncMock(return_value=True)
        self.cog = Confessions(self.bot, self.db)
        self.guild = SimpleNamespace(id=10, default_role=object(), me=object(), filesize_limit=10 * 1024 * 1024)
        self.public = self.channel(50)
        self.private = self.channel(60, private=True)
        self.guild.get_channel = {50: self.public, 60: self.private}.get
        self.db.configure_confessions(10, 50, 60)
        self.public_message = SimpleNamespace(id=100, jump_url="https://discord.com/channels/10/50/100")
        self.log_message = SimpleNamespace(id=101, edit=AsyncMock())
        self.public.send.return_value = self.public_message
        self.private.send.return_value = self.log_message
        self.modals = []

    def channel(self, channel_id, private=False):
        channel = Mock(spec=nextcord.TextChannel)
        channel.id = channel_id
        channel.guild = self.guild
        channel.mention = f"<#{channel_id}>"
        channel.send = AsyncMock()
        channel.permissions_for.side_effect = lambda member: nextcord.Permissions(
            view_channel=not (private and member is self.guild.default_role),
            send_messages=True, embed_links=True, attach_files=True)
        return channel

    async def asyncTearDown(self):
        for modal in self.modals:
            modal.stop()
        self.cog.cog_unload()
        self.db.engine.dispose()
        self.directory.cleanup()

    def interaction(self, text="A secret @everyone", payload=None, interaction_id=123):
        data = {"components": [
            {"type": 18, "component": {"type": 4, "custom_id": "confession-text", "value": text}},
            {"type": 18, "component": {"type": 19, "custom_id": "confession-image",
                                        "values": ["777"] if payload else []}},
        ], "resolved": {"attachments": {"777": payload} if payload else {}}}
        return SimpleNamespace(
            id=interaction_id, guild=self.guild, channel_id=50, data=data,
            user=SimpleNamespace(id=20, mention="<@20>", guild_permissions=nextcord.Permissions.none()),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), send_modal=AsyncMock(),
                                     _responded=True, is_done=Mock(return_value=True)),
            followup=SimpleNamespace(send=AsyncMock()), created_at=datetime.now(timezone.utc),
            _state=SimpleNamespace(http=Mock()),
        )

    def modal(self, interaction):
        modal = ConfessionModal(self.cog, interaction, (50, 60))
        self.modals.append(modal)
        return modal

    def record(self, interaction_id=123):
        with Session(self.db.engine) as session:
            return session.get(Confession, str(interaction_id))

    async def test_actual_nextcord_dispatch_logs_identity_and_posts_anonymously(self):
        interaction = self.interaction()
        order = Mock()
        order.attach_mock(self.private.send, "private")
        order.attach_mock(self.public.send, "public")
        modal = self.modal(interaction)
        await modal._scheduled_task(interaction)
        self.assertEqual([call[0] for call in order.mock_calls], ["private", "public"])
        post = self.public.send.call_args.kwargs
        self.assertEqual(post["embed"].title, "Confissão anônima #1")
        self.assertEqual(post["embed"].description, "A secret @everyone")
        self.assertNotIn("<@20>", str(post["embed"].to_dict()))
        self.assertNotIn("author", post["embed"].to_dict())
        self.assertEqual(post["allowed_mentions"].to_dict()["parse"], [])
        self.assertTrue(post["view"].is_persistent())
        audit = self.private.send.call_args.kwargs["embed"]
        self.assertIn("ID: 20", audit.fields[0].value)
        self.assertEqual(audit.fields[-1].value, self.public_message.jump_url)
        self.assertEqual((self.record().author_id, self.record().message_id, self.record().log_message_id),
                         ("20", "100", "101"))
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])

    async def test_button_opens_real_upload_modal_and_survives_reconnect(self):
        await self.cog.on_ready()
        await self.cog.on_ready()
        self.bot.add_view.assert_called_once()
        view = self.cog.persistent_view
        self.assertTrue(view.is_persistent())
        interaction = self.interaction()
        await view.submit.callback(interaction)
        modal = interaction.response.send_modal.call_args.args[0]
        self.modals.append(modal)
        payload = modal.to_dict()
        self.assertIn("ID", payload["components"][0]["content"])
        upload = payload["components"][2]["component"]
        self.assertEqual(upload["type"], 19)
        self.assertFalse(upload["required"])
        self.assertEqual(upload["max_values"], 1)
        interaction.response.defer.assert_not_awaited()

    async def test_image_reuploaded_with_neutral_filename_and_animation_preserved(self):
        for index, format in enumerate(("PNG", "JPEG", "WEBP", "GIF")):
            raw = image_bytes(format)
            interaction = self.interaction(payload={"id": "777", "size": len(raw), "filename": "author-name.jpg"},
                                           interaction_id=200 + index)
            captures = []

            async def capture(**kwargs):
                captures.append((kwargs["file"].filename, kwargs["file"].fp.read()))
                return self.log_message if len(captures) == 1 else self.public_message

            self.private.send.side_effect = capture
            self.public.send.side_effect = capture
            with patch.object(nextcord.Attachment, "read", AsyncMock(return_value=raw)):
                await self.modal(interaction)._scheduled_task(interaction)
            self.assertEqual(len(captures), 2)
            self.assertTrue(captures[0][0].startswith("confession."))
            self.assertEqual(captures[0][1], raw)
            self.assertEqual(captures[0], captures[1])

    async def test_invalid_text_and_uploads_never_post(self):
        for text, payload, raw in (
            ("   ", None, b""), ("x" * 4001, None, b""),
            ("secret", {"size": MAX_IMAGE_BYTES + 1}, b""),
            ("secret", {"id": "777", "size": 5, "filename": "fake.png"}, b"hello"),
        ):
            interaction = self.interaction(text, payload)
            with patch.object(nextcord.Attachment, "read", AsyncMock(return_value=raw)):
                await self.modal(interaction)._scheduled_task(interaction)
            self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])
        self.private.send.assert_not_awaited()
        self.public.send.assert_not_awaited()
        self.assertIsNone(self.record())

    async def test_missing_resolved_attachment_and_multiple_files_rejected(self):
        for values in (["777"], ["777", "888"]):
            interaction = self.interaction()
            interaction.data["components"][1]["component"]["values"] = values
            await self.modal(interaction)._scheduled_task(interaction)
        self.private.send.assert_not_awaited()

    async def test_log_failure_prevents_publication(self):
        self.private.send.side_effect = http_error()
        interaction = self.interaction()
        await self.modal(interaction)._scheduled_task(interaction)
        self.public.send.assert_not_awaited()
        self.assertIn("não foi publicada", interaction.followup.send.call_args.args[0])
        self.assertEqual(self.record().author_id, "20")
        self.assertIsNone(self.record().message_id)

    async def test_public_failure_keeps_attribution_and_marks_log(self):
        self.public.send.side_effect = http_error()
        interaction = self.interaction()
        await self.modal(interaction)._scheduled_task(interaction)
        self.assertIn("Falha", self.log_message.edit.call_args.kwargs["embed"].footer.text)
        self.assertEqual(self.record().log_message_id, "101")
        self.assertIsNone(self.record().message_id)
        self.assertIn("não consegui publicar", interaction.followup.send.call_args.args[0])

    async def test_log_edit_failure_does_not_report_public_post_as_failed(self):
        self.log_message.edit.side_effect = http_error()
        interaction = self.interaction()
        with self.assertLogs("cogs.confessions", level="ERROR"):
            await self.modal(interaction)._scheduled_task(interaction)
        self.assertIn("enviada!", interaction.followup.send.call_args.args[0])
        self.assertEqual(self.record().message_id, "100")

    async def test_duplicate_modal_submission_posts_once(self):
        interaction = self.interaction()
        modal = self.modal(interaction)
        await asyncio.gather(modal.callback(interaction), modal.callback(interaction))
        self.public.send.assert_awaited_once()
        self.private.send.assert_awaited_once()

    async def test_wrong_user_guild_and_changed_config_rejected(self):
        for change in ("user", "guild", "config"):
            interaction = self.interaction()
            modal = self.modal(interaction)
            if change == "user":
                interaction.user.id = 30
            elif change == "guild":
                interaction.guild = None
            else:
                self.db.configure_confessions(10, 70, 60)
            await modal.callback(interaction)
        self.public.send.assert_not_awaited()
        self.private.send.assert_not_awaited()

    async def test_missing_channels_public_logs_and_missing_bot_permissions_rejected(self):
        for change in ("deleted", "public", "permission", "same"):
            interaction = self.interaction()
            if change == "deleted":
                self.guild.get_channel = lambda _: None
            elif change == "public":
                self.guild.get_channel = {50: self.public, 60: self.private}.get
                self.private.permissions_for.side_effect = lambda _: nextcord.Permissions.all()
            elif change == "permission":
                self.private.permissions_for.side_effect = lambda _: nextcord.Permissions.none()
            else:
                self.db.configure_confessions(10, 50, 50)
            await self.modal(interaction).callback(interaction)
        self.public.send.assert_not_awaited()
        self.private.send.assert_not_awaited()

    async def test_setup_requires_admin_and_does_not_configure_after_send_failure(self):
        ctx = SimpleNamespace(guild=self.guild, author=self.interaction().user,
                              bot=self.bot, command=self.cog.confess, send=AsyncMock())
        with self.assertRaises(commands.MissingPermissions):
            await self.cog.confess.can_run(ctx)
        ctx.author.guild_permissions = nextcord.Permissions(administrator=True)
        self.assertTrue(await self.cog.confess.can_run(ctx))
        await Confessions.confess.callback(self.cog, ctx, self.public, self.private)
        self.assertTrue(self.public.send.call_args.kwargs["view"].is_persistent())
        self.db.configure_confessions(10, 70, 60)
        self.public.send.side_effect = http_error()
        with self.assertRaises(nextcord.HTTPException):
            await Confessions.confess.callback(self.cog, ctx, self.public, self.private)
        self.assertEqual(self.db.confession_channels(10), (70, 60))

    def test_numbers_and_attribution_persist_and_concurrent_reservations_are_unique(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            numbers = list(pool.map(lambda i: self.db.reserve_confession(10, 20, i, (50, 60)), range(12)))
        self.assertEqual(sorted(numbers), list(range(1, 13)))
        reopened = Database(self.url)
        try:
            self.assertEqual(reopened.confession_channels(10), (50, 60))
            reopened.configure_confessions(10, 70, 80)
            self.assertEqual(reopened.reserve_confession(10, 20, 99, (70, 80)), 13)
            reopened.configure_confessions(11, 90, 91)
            self.assertEqual(reopened.reserve_confession(11, 20, 100, (90, 91)), 1)
            with self.assertRaises(EconomyError):
                reopened.reserve_confession(11, 20, 100, (90, 91))
        finally:
            reopened.engine.dispose()


if __name__ == "__main__":
    unittest.main()
