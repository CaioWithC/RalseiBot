"""Exercise Discord option parsing and shared command execution without login."""
import asyncio
from datetime import datetime, timezone
from io import BytesIO
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ["BOT_DATABASE_URL"] = "sqlite:///:memory:"

import nextcord
from nextcord.ext import commands
from PIL import Image

from db import Database
from main import create_bot, error_message
from cogs.game_rules import Blackjack
from cogs.social import MAX_UPLOAD_BYTES


def png():
    output = BytesIO()
    Image.new("RGB", (40, 30), "orange").save(output, format="PNG")
    return output.getvalue()


def user(user_id=111111111111111111, admin=False):
    avatar = SimpleNamespace(read=AsyncMock(return_value=png()))
    avatar.with_size = lambda _: avatar
    avatar.with_static_format = lambda _: avatar
    return SimpleNamespace(id=user_id, display_name=f"Player {user_id}", bot=False,
                           guild_permissions=nextcord.Permissions(administrator=admin),
                           display_avatar=avatar)


class SlashCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database("sqlite:///:memory:")
        self.bot = create_bot()
        self.bot._connection.user = SimpleNamespace(id=999)
        self.author = user()
        self.member = user(222222222222222222)
        self.db.add_balance(self.author.id, 10_000)
        self.economy_patch = patch("cogs.economy.database", self.db)
        self.economy_patch.start()
        for name in ("Games", "Leaderboard", "Social", "Relationships", "Roleplay", "Tickets"):
            self.bot.get_cog(name).storage = self.db
        self.apps = {command.name: command for command in self.bot.get_all_application_commands()}
        self.views = []
        self.seconds = 0

    async def asyncTearDown(self):
        for view in self.views:
            view.stop()
        self.economy_patch.stop()
        await self.bot.close()
        self.db.engine.dispose()

    def interaction(self, name, *, author=None, guild=True):
        author = author or self.author
        received = asyncio.Event()
        response = SimpleNamespace(is_done=Mock(return_value=False))

        async def defer():
            response.is_done.return_value = True

        interaction = SimpleNamespace(
            id=123456789012345678, user=author, client=self.bot,
            created_at=datetime.fromtimestamp(1_800_000_000 + self.seconds, timezone.utc),
            channel=SimpleNamespace(id=123, permissions_for=lambda member: member.guild_permissions),
            guild=SimpleNamespace(id=321, get_member=lambda _: None) if guild else None,
            response=response, data={"options": []}, received=received, sent=[], images=[],
            application_command=self.apps[name.split()[0]],
        )
        interaction._set_application_command = lambda command: setattr(interaction, "application_command", command)
        interaction._resolve_users = lambda: [author, self.member]

        async def capture(content=None, **kwargs):
            self.assertTrue(response.is_done())
            interaction.sent.append({"content": content, **kwargs})
            if "file" in kwargs:
                interaction.images.append(kwargs["file"].fp.read())
            if "view" in kwargs:
                self.views.append(kwargs["view"])
            received.set()
            return SimpleNamespace(edit=AsyncMock())

        response.defer = AsyncMock(side_effect=defer)
        response.send_message = AsyncMock()
        interaction.followup = SimpleNamespace(send=AsyncMock(side_effect=capture))
        return interaction

    async def slash(self, name, *, author=None, guild=True, **values):
        interaction = self.interaction(name, author=author, guild=guild)
        parts = name.split()
        root = self.apps[parts[0]]
        target = root.children[parts[1]] if len(parts) > 1 else root
        options = []
        for key, value in values.items():
            option_type = target.options[key].type.value
            if option_type == 6:
                value = str(value.id)
            elif option_type == 11:
                interaction.data["resolved"] = {"attachments": {value["id"]: value}}
                value = value["id"]
            options.append({"name": key, "value": value, "type": option_type})
        interaction.data["options"] = ([{"name": parts[1], "type": 1, "options": options}]
                                       if len(parts) > 1 else options)
        await root.call(self.bot._connection, interaction)
        await asyncio.wait_for(interaction.received.wait(), timeout=3)
        await asyncio.sleep(0)  # Deliver completion listeners scheduled by Bot.invoke.
        interaction.response.defer.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()
        return interaction

    async def prefix_context(self, content, *, author=None, guild=True):
        interaction = self.interaction("ping", author=author, guild=guild)
        message = SimpleNamespace(content=content, author=interaction.user, guild=interaction.guild,
                                  channel=interaction.channel, attachments=[], edited_at=None,
                                  created_at=interaction.created_at, _state=self.bot._connection)
        ctx = await self.bot.get_context(message)
        ctx.send = AsyncMock()
        return ctx

    async def test_every_prefix_command_has_a_registered_slash_equivalent(self):
        registered = set()
        for app in self.apps.values():
            payload = app.get_payload(None)
            self.assertLessEqual(len(payload["description"]), 100)
            if app.children:
                registered.update(f"{app.name} {child}" for child in app.children)
            else:
                registered.add(app.name)
        expected = {"profile view" if c.qualified_name == "profile" else c.qualified_name
                    for c in self.bot.walk_commands()}
        self.assertEqual(registered, expected)
        self.assertEqual(self.bot.command_prefix, "r.")
        for command in self.bot.walk_commands():
            for alias in command.aliases:
                prefix = f"{command.parent.qualified_name} " if command.parent else ""
                self.assertIs(self.bot.get_command(prefix + alias), command)
        for name in ("pay", "work", "addbalance", "setbalance", "resetbalance", "activity", "close"):
            self.assertEqual(self.apps[name].get_payload(None)["contexts"], [0])
        for name in ("addbalance", "setbalance", "resetbalance", "activity"):
            self.assertEqual(self.apps[name].get_payload(None)["default_member_permissions"], "8")
        for name in ("pay", "setbalance", "addbalance", "slots", "blackjack", "mines"):
            self.assertEqual(self.apps[name].options["amount"].type, nextcord.ApplicationCommandOptionType.string)
        self.assertEqual(self.apps["profile"].children["background"].options["image"].type,
                         nextcord.ApplicationCommandOptionType.attachment)

    async def test_roleplay_prefix_and_slash_share_rotation_cooldowns_and_affinity(self):
        from cogs.roleplay import GIFS
        self.db.marry(self.author.id, self.member.id)
        for name, alias in (("kiss", "beijar"), ("hug", "abracar"), ("pat", "carinho")):
            self.assertEqual(self.apps[name].get_payload(None)["contexts"], [0])
            result = await self.slash(name, member=self.member)
            first_gif = result.sent[0]["embed"].image.url
            self.assertIn(first_gif, GIFS[name])
            ctx = await self.prefix_context(f"r.{alias} <@{self.member.id}>")
            with self.assertRaises(commands.CommandOnCooldown):
                await ctx.command.invoke(ctx)
            self.seconds += 6
            ctx = await self.prefix_context(f"r.{alias} <@{self.member.id}>")
            with patch.object(commands.MemberConverter, "convert", new=AsyncMock(return_value=self.member)):
                await ctx.command.invoke(ctx)
            next_gif = ctx.send.call_args.kwargs["embed"].image.url
            self.assertIn(next_gif, GIFS[name])
            self.assertNotEqual(next_gif, first_gif)
            result = await self.slash(name, member=self.member)
            self.assertIn("Aguarde", result.sent[0]["content"])
            result = await self.slash(name, member=self.member, guild=False)
            self.assertIn("servidor", result.sent[0]["content"])
        self.assertTrue(6 <= self.db.marriage(self.author.id)["affinity"] <= 18)

    async def test_reciprocate_swaps_participants_rotates_gif_and_prevents_duplicate_clicks(self):
        from cogs.roleplay import GIFS
        self.db.marry(self.author.id, self.member.id)
        for action in GIFS:
            original = await self.slash(action, member=self.member)
            view = original.sent[0]["view"]
            self.assertEqual(view.children[0].label, "Retribuir")
            outsider = self.interaction(action, author=self.author)
            await view.reciprocate.callback(outsider)
            outsider.response.send_message.assert_awaited_once()
            self.assertTrue(outsider.response.send_message.call_args.kwargs["ephemeral"])
            outsider.response.defer.assert_not_awaited()
            first = self.interaction(action, author=self.member)
            second = self.interaction(action, author=self.member)
            first.message = second.message = view.message
            with patch("cogs.roleplay.random.randint", return_value=2):
                before = self.db.marriage(self.author.id)["affinity"]
                await asyncio.gather(view.reciprocate.callback(first), view.reciprocate.callback(second))
            self.assertEqual(self.db.marriage(self.author.id)["affinity"], before + 2)
            embed = first.sent[0]["embed"]
            self.assertLess(embed.description.index(str(self.member.id)), embed.description.index(str(self.author.id)))
            self.assertIn(embed.image.url, GIFS[action])
            self.assertNotEqual(embed.image.url, original.sent[0]["embed"].image.url)
            self.assertTrue(view.reciprocate.disabled)
            self.assertTrue(view.is_finished())
            self.assertIn("já foi retribuída", second.sent[0]["content"])
            # The newly created button lets the original sender reply, subject to cooldown.
            reply_view = first.sent[0]["view"]
            reply = self.interaction(action, author=self.author)
            reply.message = reply_view.message
            await reply_view.reciprocate.callback(reply)
            await asyncio.wait_for(reply.received.wait(), timeout=3)
            self.assertIn("Aguarde", reply.sent[0]["content"])
            self.assertFalse(reply_view.done)
            self.seconds += 6
            retry = self.interaction(action, author=self.author)
            retry.message = reply_view.message
            await reply_view.reciprocate.callback(retry)
            retry_gif = retry.sent[0]["embed"].image.url
            self.assertIn(retry_gif, GIFS[action])
            self.assertNotIn(retry_gif, (original.sent[0]["embed"].image.url, embed.image.url))
            self.assertTrue(reply_view.done)

    async def test_reciprocate_timeout_disables_button_without_awarding_points(self):
        original = await self.slash("hug", member=self.member)
        view = original.sent[0]["view"]
        await view.on_timeout()
        self.assertTrue(view.reciprocate.disabled)
        view.message.edit.assert_awaited_once_with(view=view)
        click = self.interaction("hug", author=self.member)
        await view.reciprocate.callback(click)
        self.assertIn("expirou", click.sent[0]["content"])
        self.assertNotIn("embed", click.sent[0])

    async def test_connection_registers_global_slash_commands(self):
        with patch.object(self.bot, "sync_application_commands", new_callable=AsyncMock) as sync:
            await self.bot.on_connect()
        sync.assert_awaited_once()
        self.assertIsNone(sync.call_args.kwargs["guild_id"])
        self.assertTrue(sync.call_args.kwargs["register_new"])
        self.assertTrue(sync.call_args.kwargs["update_known"])

    async def test_ping_balance_daily_and_work_use_existing_handlers(self):
        self.assertEqual((await self.slash("ping")).sent[0]["content"], "Pong!")
        self.assertIn("10,000", (await self.slash("balance")).sent[0]["content"])
        with patch("cogs.economy.random.randint", return_value=5000):
            await self.slash("daily")
            await self.slash("work")
        self.assertEqual(self.db.balance(self.author.id), 20_000)
        result = await self.slash("daily")
        self.assertIn("diária", result.sent[0]["content"])
        self.assertEqual(self.db.balance(self.author.id), 20_000)

    async def test_slash_proposal_requires_both_clicks_and_marriage_status_works_in_both_formats(self):
        result = await self.slash("marry", member=self.member)
        view = result.sent[0]["view"]
        self.assertIsNotNone(view.message)
        self.assertEqual(view.confirmed, set())
        self.assertIsNone(self.db.marriage(self.author.id))

        def click(person):
            return SimpleNamespace(user=person, message=view.message,
                                   response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                                   followup=SimpleNamespace(send=AsyncMock()))

        await view.confirm.callback(click(self.member))
        self.assertIsNone(self.db.marriage(self.author.id))
        with patch("db.time.time", return_value=1800000000):
            await view.confirm.callback(click(self.author))
        result = await self.slash("marriage", member=self.member)
        embed = result.sent[0]["embed"]
        self.assertEqual(embed.fields[0].value, "<t:1800000000:F>")
        self.assertEqual(embed.fields[1].value, "<t:1800000000:R>")
        ctx = await self.prefix_context("r.casamento")
        await ctx.command.invoke(ctx)
        self.assertEqual(ctx.send.call_args.kwargs["embed"].to_dict(), embed.to_dict())

    async def test_prefix_proposal_alias_and_slash_guild_self_bot_restrictions(self):
        result = await self.slash("marry", guild=False, member=self.member)
        self.assertIn("servidor", result.sent[0]["content"])
        result = await self.slash("marry", member=self.author)
        self.assertIn("si mesmo", result.sent[0]["content"])
        self.seconds += 11
        self.member.bot = True
        result = await self.slash("marry", member=self.member)
        self.assertIn("Bots", result.sent[0]["content"])
        self.member.bot = False
        self.seconds += 11
        ctx = await self.prefix_context(f"r.casar <@{self.member.id}>")
        with patch.object(commands.MemberConverter, "convert", new=AsyncMock(return_value=self.member)):
            await ctx.command.invoke(ctx)
        view = ctx.send.call_args.kwargs["view"]
        self.views.append(view)
        self.assertEqual(view.participants, (self.author.id, self.member.id))
        self.assertEqual(view.confirmed, set())
        result = await self.slash("marriage")
        self.assertIn("Não há casamento", result.sent[0]["embed"].description)
        self.assertEqual(self.apps["marry"].get_payload(None)["contexts"], [0])

    async def test_ship_single_target_explicit_pair_and_prefix_alias_keep_same_score(self):
        with patch("db.secrets.randbelow", return_value=87) as random:
            result = await self.slash("ship", first=self.member)
            self.assertIn("87%", result.sent[0]["content"])
            with Image.open(BytesIO(result.images[0])) as image:
                self.assertEqual(image.size, (1000, 680))
                image.verify()
            self.seconds += 6
            reverse = await self.slash("ship", first=self.member, second=self.author)
            self.assertIn("87%", reverse.sent[0]["content"])
            self.seconds += 6
            ctx = await self.prefix_context(f"r.shippar <@{self.member.id}>")
            with patch.object(commands.UserConverter, "convert", new=AsyncMock(return_value=self.member)):
                await ctx.command.invoke(ctx)
            self.assertIn("87%", ctx.send.call_args.kwargs["content"])
            self.assertEqual(ctx.send.call_args.kwargs["file"].filename, "ship.png")
            random.assert_called_once_with(101)
        self.seconds += 6
        # Explicitly select two people other than the author.
        third = self.bot._connection.store_user({"id": "333333333333333333", "username": "Susie", "discriminator": "0", "avatar": None})
        with patch.object(nextcord.Asset, "read", new=AsyncMock(return_value=png())), \
                patch("db.secrets.randbelow", return_value=42):
            result = await self.slash("ship", first=self.member, second=third)
        self.assertIn(f"<@{self.member.id}>", result.sent[0]["content"])
        self.assertIn(f"<@{third.id}>", result.sent[0]["content"])
        self.assertNotIn(f"<@{self.author.id}>", result.sent[0]["content"])
        self.assertIn("42%", result.sent[0]["content"])

    async def test_prefix_and_slash_share_per_user_cooldowns_in_both_directions(self):
        for name, prefix, options, cooldown in (
            ("work", "r.work", {}, 7200), ("freelance", "r.freelas", {}, 600), ("rich", "r.top", {}, 5),
            ("slots", "r.slot 100", {"amount": "100"}, 3),
            ("profile view", "r.perfil", {}, 5),
        ):
            with self.subTest(command=name):
                ctx = await self.prefix_context(prefix)
                await ctx.command.invoke(ctx)
                result = await self.slash(name, **options)
                self.assertIn("Aguarde", result.sent[0]["content"])
                self.db.add_balance(self.member.id, 1000)
                other = await self.slash(name, author=self.member, **options)
                self.assertNotIn("Aguarde", other.sent[0]["content"] or "")
                self.seconds += cooldown + 1
                expired = await self.slash(name, **options)
                self.assertNotIn("Aguarde", expired.sent[0]["content"] or "")
                ctx = await self.prefix_context(prefix)
                with self.assertRaises(commands.CommandOnCooldown):
                    await ctx.command.invoke(ctx)
                self.seconds += cooldown + 1

    async def test_daily_shares_midnight_reset_and_relative_timestamps_across_both_formats(self):
        midnight = int(datetime.fromisoformat("2026-09-08T03:00:00+00:00").timestamp())
        with patch("cogs.economy.random.randint", return_value=5000), patch("db.time.time", return_value=midnight - 1):
            await self.slash("daily")
            ctx = await self.prefix_context("r.daily")
            await self.bot.invoke(ctx)
            await asyncio.sleep(0)
            self.assertIn(f"<t:{midnight}:R>", ctx.send.call_args.args[0])
            self.assertEqual(self.db.balance(self.author.id), 15000)
        with patch("cogs.economy.random.randint", return_value=5000), patch("db.time.time", return_value=midnight):
            ctx = await self.prefix_context("r.daily")
            await self.bot.invoke(ctx)
            await asyncio.sleep(0)
            self.assertIn("recebeu", ctx.send.call_args.args[0])
            result = await self.slash("daily")
            self.assertIn(f"<t:{midnight + 86400}:R>", result.sent[0]["content"])
            self.assertIn("00:00 GMT-3", result.sent[0]["content"])
            self.assertNotIn("`<t:", result.sent[0]["content"])
            self.assertEqual(self.db.balance(self.author.id), 20000)

    async def test_command_cooldowns_show_same_relative_deadline_in_prefix_and_slash(self):
        for name, prefix, duration in (("work", "r.work", 7200), ("freelance", "r.freelas", 600)):
            with self.subTest(command=name):
                self.seconds = 0
                ctx = await self.prefix_context(prefix)
                await ctx.command.invoke(ctx)
                self.seconds = 5
                expected = f"<t:{1800000000 + duration}:R>"
                result = await self.slash(name)
                self.assertIn(expected, result.sent[0]["content"])
                ctx = await self.prefix_context(prefix)
                await self.bot.invoke(ctx)
                await asyncio.sleep(0)
                self.assertIn(expected, ctx.send.call_args.args[0])
                self.assertNotIn("segundos", ctx.send.call_args.args[0])

    def test_cooldown_timestamp_rounds_up_and_unwraps_errors(self):
        error = commands.CommandOnCooldown(commands.Cooldown(1, 10), 5.4, commands.BucketType.user)
        wrapped = commands.CommandInvokeError(error)
        self.assertIn("<t:1800000006:R>", error_message(wrapped, "/work", now=1800000000.2))
        with patch("main.time.time", return_value=1800000000.2):
            self.assertIn("<t:1800000006:R>", error_message(error, "/work"))

    async def test_admin_checks_run_at_execution_and_reject_direct_messages(self):
        for name in ("addbalance", "setbalance", "resetbalance"):
            values = {"member": self.member}
            if name != "resetbalance":
                values["amount"] = "100"
            result = await self.slash(name, **values)
            self.assertIn("administrador", result.sent[0]["content"])
            result = await self.slash(name, guild=False, **values)
            self.assertIn("servidor", result.sent[0]["content"])
            self.assertEqual(self.db.balance(self.member.id), 0)
        for name, options in (("work", {}), ("pay", {"member": self.member, "amount": "100"})):
            result = await self.slash(name, guild=False, **options)
            self.assertIn("servidor", result.sent[0]["content"])
        self.assertEqual(self.db.balance(self.author.id), 10_000)

    async def test_close_ticket_prefix_aliases_and_slash(self):
        self.db.configure_tickets(321, 50)
        channel = Mock(spec=nextcord.TextChannel)
        channel.id = 123
        channel.category_id = 50
        channel.topic = f"ticket-owner:{self.author.id}"
        channel.delete = AsyncMock()
        channel.permissions_for.return_value = nextcord.Permissions.none()
        for name in ("close", "fechar", "closeticket"):
            ctx = await self.prefix_context(f"r.{name}")
            ctx.channel = channel
            await ctx.command.invoke(ctx)
        interaction = self.interaction("close")
        interaction.channel = channel
        await self.apps["close"].call(self.bot._connection, interaction)
        self.assertEqual(channel.delete.await_count, 4)
        self.assertIn("excluindo", interaction.sent[0]["content"])
        interaction.response.defer.assert_awaited_once()

    async def test_close_ticket_rejects_direct_messages_in_both_formats(self):
        result = await self.slash("close", guild=False)
        self.assertIn("servidor", result.sent[0]["content"])
        ctx = await self.prefix_context("r.close", guild=False)
        with self.assertRaises(commands.NoPrivateMessage):
            await ctx.command.invoke(ctx)

    async def accept_payment(self, view):
        self.views.append(view)
        for participant in (self.author, self.member):
            interaction = SimpleNamespace(
                user=participant, message=view.message,
                response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            await view.confirm.callback(interaction)

    async def test_admin_commands_and_transfers_resolve_member_and_exact_amount(self):
        self.author.guild_permissions.administrator = True
        amount = 8_999_999_999_999_999
        await self.slash("setbalance", member=self.member, amount=str(amount))
        self.assertEqual(self.db.balance(self.member.id), amount)
        await self.slash("resetbalance", member=self.member)
        self.assertEqual(self.db.balance(self.member.id), 0)
        await self.slash("addbalance", member=self.member, amount="300")
        result = await self.slash("pay", member=self.member, amount="100")
        self.assertEqual(self.db.balance(self.member.id), 300)
        await self.accept_payment(result.sent[0]["view"])
        self.assertEqual(self.db.balance(self.member.id), 400)
        self.assertEqual(self.db.balance(self.author.id), 9900)

    async def test_activity_command_works_with_slash_and_prefix_aliases_and_checks_permissions(self):
        cog = self.bot.get_cog("Activities")
        result = await self.slash("activity", text="Evento no reino!")
        self.assertIn("administrador", result.sent[0]["content"])
        self.assertIsNone(cog.override)
        self.author.guild_permissions.administrator = True
        result = await self.slash("activity", guild=False, text="Evento no reino!")
        self.assertIn("servidor", result.sent[0]["content"])
        self.assertIsNone(cog.override)
        await self.slash("activity", text="Evento no reino!")
        self.assertEqual(cog.override.text, "Evento no reino!")
        ctx = await self.prefix_context("r.atividade reset")
        await self.bot.invoke(ctx)
        await asyncio.sleep(0)  # Deliver the registered completion listener.
        self.assertIsNone(cog.override)
        ctx = await self.prefix_context("r.status Caio merece um bolo!")
        await self.bot.invoke(ctx)
        await asyncio.sleep(0)
        self.assertEqual(cog.override.text, "Caio merece um bolo!")
        await self.slash("activity", text="reset")
        self.assertIsNone(cog.override)
        self.author.guild_permissions.administrator = False
        ctx = await self.prefix_context("r.activity Sem permissão")
        with self.assertRaises(commands.MissingPermissions):
            await ctx.command.invoke(ctx)

    async def test_admin_reactions_receive_shared_completion_events_once_for_both_formats(self):
        self.author.guild_permissions.administrator = True
        cog = self.bot.get_cog("Activities")
        await self.slash("ping")
        self.assertEqual(cog.completed_commands, 1)
        self.assertIn("/ping", cog.override.text)
        ctx = await self.prefix_context("r.ping")
        await self.bot.invoke(ctx)
        await asyncio.sleep(0)
        self.assertEqual(cog.completed_commands, 2)
        self.assertIn("r.ping", cog.override.text)
        original = cog.override
        await self.slash("pay", member=self.member, amount="invalid")
        self.assertEqual(cog.completed_commands, 2)
        self.assertIs(cog.override, original)
        self.author.guild_permissions.administrator = False
        await self.slash("ping")
        self.assertEqual(cog.completed_commands, 3)
        self.assertIs(cog.override, original)

    async def test_pay_suffixes_transfer_exact_amounts_in_both_formats_and_aliases(self):
        for name in ("pay", "pix", "pagar", "transferir"):
            for raw, amount in (("100", 100), ("1k", 1000), ("1.5K", 1500),
                                ("2m", 2_000_000), ("1.25M", 1_250_000)):
                with self.subTest(command=name, amount=raw):
                    self.db.set_balance(self.author.id, amount * 2)
                    self.db.set_balance(self.member.id, 0)
                    ctx = await self.prefix_context(f"r.{name} <@{self.member.id}> {raw}")
                    with patch.object(commands.MemberConverter, "convert", new=AsyncMock(return_value=self.member)):
                        await ctx.command.invoke(ctx)
                    self.assertEqual(self.db.balance(self.author.id), amount * 2)
                    self.assertEqual(self.db.balance(self.member.id), 0)
                    view = ctx.send.call_args.kwargs["view"]
                    await self.accept_payment(view)
                    self.assertEqual(self.db.balance(self.author.id), amount)
                    self.assertEqual(self.db.balance(self.member.id), amount)
                    self.assertIn(f"transferiu {amount:,} D$", view.content())
                    result = await self.slash("pay", member=self.member, amount=raw)
                    self.assertEqual(self.db.balance(self.author.id), amount)
                    await self.accept_payment(result.sent[0]["view"])
                    self.assertIn(f"transferiu {amount:,} D$", result.sent[0]["view"].content())
                    self.assertEqual(self.db.balance(self.author.id), 0)
                    self.assertEqual(self.db.balance(self.member.id), amount * 2)

    async def test_pay_invalid_suffixes_and_insufficient_balance_leave_wallets_unchanged(self):
        for raw in ("0K", "-1M", "0.0001K", "1.5", "1KK", "1e3", "half", "all", "2M"):
            with self.subTest(amount=raw):
                ctx = await self.prefix_context(f"r.pay <@{self.member.id}> {raw}")
                with patch.object(commands.MemberConverter, "convert", new=AsyncMock(return_value=self.member)):
                    with self.assertRaises(commands.CommandError):
                        await ctx.command.invoke(ctx)
                ctx.send.assert_not_awaited()
                result = await self.slash("pay", member=self.member, amount=raw)
                self.assertNotIn("transferiu", result.sent[0]["content"])
                self.assertEqual(self.db.balance(self.author.id), 10_000)
                self.assertEqual(self.db.balance(self.member.id), 0)

    async def test_bad_input_and_economy_errors_respond_without_spending(self):
        for name, options, expected in (
            ("pay", {"member": self.member, "amount": "1.5"}, "/pay"),
            ("pay", {"member": self.member, "amount": "999999"}, "saldo"),
            ("slots", {"amount": "invalid"}, "/slots"),
            ("blackjack", {"amount": "0"}, "/blackjack"),
            ("mines", {"amount": "100", "mine_count": 16}, "1 e 15"),
            ("rich", {"page": 2}, "página"),
        ):
            with self.subTest(command=name):
                result = await self.slash(name, **options)
                self.assertIn(expected, result.sent[0]["content"])
                self.assertEqual(self.db.balance(self.author.id), 10_000)

    async def test_game_amount_shortcuts_survive_slash_option_conversion(self):
        for name in ("blackjack", "mines"):
            for raw, expected in (("10k", 10000), ("1.5m", 1500000), ("HALF", "half"),
                                  ("ALL", "all"), (str(10 ** 80 + 123), 10 ** 80 + 123)):
                received = []

                async def start(ctx, amount, *args, **kwargs):
                    received.append(amount)
                    await ctx.send("Started")

                with patch.object(self.bot.get_cog("Games"), "start_game", side_effect=start):
                    await self.slash(name, amount=raw)
                self.assertEqual(received, [expected])
        with patch("cogs.games.RNG.choice", return_value="💎"):
            await self.slash("slots", amount="ALL")
        self.assertEqual(self.db.balance(self.author.id), 100_000)

    async def test_mines_returns_editable_message_for_buttons_and_timeout(self):
        result = await self.slash("mines", amount="half")
        view = result.sent[0]["view"]
        self.assertEqual(view.owner_id, self.author.id)
        self.assertEqual(view.game.stake, 5000)
        self.assertTrue(result.sent[0]["wait"])
        self.assertIsNotNone(view.message)
        self.assertEqual(self.db.balance(self.author.id), 5000)
        intruder = SimpleNamespace(user=self.member, response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(intruder))
        await view.on_timeout()
        self.assertEqual(self.db.balance(self.author.id), 10000)
        view.message.edit.assert_awaited_once()
        result = await self.slash("mines", amount="100", mine_count=5)
        self.assertEqual(len(result.sent[0]["view"].game.mines), 5)

    async def test_blackjack_button_settlement_edits_slash_message(self):
        # Deal player 19, dealer 18, avoiding an immediate natural.
        cards = list(reversed([("10", "♠"), ("10", "♥"), ("9", "♠"), ("8", "♥")]))
        with patch("cogs.games.Blackjack", side_effect=lambda amount: Blackjack(amount, cards)):
            result = await self.slash("blackjack", amount="100")
        view = result.sent[0]["view"]
        click = SimpleNamespace(user=self.author, message=view.message,
                                response=SimpleNamespace(defer=AsyncMock()),
                                followup=SimpleNamespace(send=AsyncMock()))
        await view.act(click, view.game.stand)
        view.message.edit.assert_awaited_once()
        self.assertEqual(self.db.balance(self.author.id), 10100)
        self.assertTrue(view.done)

    async def test_ranking_and_own_or_selected_profile_send_valid_images(self):
        for name, options, filename in (("rich", {}, "rich-list.png"),
                                         ("profile view", {}, "profile.png"),
                                         ("profile view", {"member": self.member}, "profile.png")):
            self.seconds += 6
            result = await self.slash(name, **options)
            self.assertEqual(result.sent[0]["file"].filename, filename)
            with Image.open(BytesIO(result.images[0])) as image:
                self.assertEqual(image.format, "PNG")
                image.verify()
        self.author.display_avatar.read.assert_awaited_once()
        self.member.display_avatar.read.assert_awaited_once()

    async def test_profile_color_and_bio_preserve_spaces_quotes_and_newlines(self):
        text = 'Gosto de "aventuras" e amigos!\nMais uma linha.'
        await self.slash("profile color", value="#77e5bc")
        await self.slash("profile about", text=text)
        profile = self.db.profile(self.author.id)
        self.assertEqual(profile["color"], "#77E5BC")
        self.assertEqual(profile["about"], text)
        await self.slash("profile about", text="reset")
        self.assertEqual(self.db.profile(self.author.id)["about"], "")
        self.assertEqual(self.db.profile(self.member.id)["about"], "")

    async def test_background_attachment_upload_reset_validation_and_shared_cooldown(self):
        attachment = {"id": "123", "filename": "background.png", "size": len(png()),
                      "url": "https://cdn.discordapp.com/test.png", "proxy_url": "https://cdn.discordapp.com/test.png"}
        with patch.object(nextcord.Attachment, "read", new=AsyncMock(return_value=png())) as read:
            await self.slash("profile background", image=attachment)
            read.assert_awaited_once()
        stored = self.db.profile(self.author.id)["background"]
        with Image.open(BytesIO(stored)) as image:
            self.assertEqual(image.size, (1000, 400))
        ctx = await self.prefix_context("r.perfil fundo reset")
        with self.assertRaises(commands.CommandOnCooldown):
            await ctx.command.invoke(ctx)
        self.seconds += 6
        attachment["size"] = MAX_UPLOAD_BYTES + 1
        with patch.object(nextcord.Attachment, "read", new_callable=AsyncMock) as read:
            result = await self.slash("profile background", image=attachment)
            self.assertIn("8 MB", result.sent[0]["content"])
            read.assert_not_awaited()
        self.assertEqual(self.db.profile(self.author.id)["background"], stored)
        self.seconds += 6
        await self.slash("profile background", action="reset")
        self.assertIsNone(self.db.profile(self.author.id)["background"])
        self.seconds += 6
        result = await self.slash("profile background")
        self.assertIn("/profile background", result.sent[0]["content"])

    async def test_help_lists_both_forms_and_resolves_prefix_aliases(self):
        result = await self.slash("help")
        embeds = [message["embed"] for message in result.sent]
        fields = [field for embed in embeds for field in embed.fields]
        self.assertEqual(len(fields), sum(1 for _ in self.bot.walk_commands()))
        for embed in embeds:
            self.assertLessEqual(len(embed.fields), 25)
            self.assertLessEqual(len(embed), 6000)
        self.assertIn("/profile view", " ".join(field.name for field in fields))
        ctx = await self.prefix_context("r.help")
        await ctx.command.invoke(ctx)
        self.assertEqual([call.kwargs["embed"].to_dict() for call in ctx.send.call_args_list],
                         [embed.to_dict() for embed in embeds])
        for name in ("minas", "profile background", "/profile view", "r.perfil cor"):
            result = await self.slash("help", command=name)
            self.assertIn("Ajuda:", result.sent[0]["embed"].title)
        result = await self.slash("help", command="unknown")
        self.assertIn("não encontrado", result.sent[0]["content"])

    async def test_global_checks_and_invocation_hooks_are_not_bypassed(self):
        before, after = AsyncMock(), AsyncMock()
        self.bot.before_invoke(before)
        self.bot.after_invoke(after)
        await self.slash("ping")
        before.assert_awaited_once()
        after.assert_awaited_once()
        self.bot.add_check(lambda ctx: False, call_once=True)
        result = await self.slash("ping")
        self.assertIn("não pode", result.sent[0]["content"])
        before.assert_awaited_once()

    async def test_unexpected_errors_use_fallback_for_prefix_and_application_errors(self):
        with patch.object(self.db, "balance", side_effect=RuntimeError("database unavailable")), \
                self.assertLogs("main", level="ERROR"):
            result = await self.slash("balance")
        self.assertIn("Tente novamente", result.sent[0]["content"])
        interaction = self.interaction("ping")
        with self.assertLogs("main", level="ERROR"):
            await self.bot.on_application_command_error(interaction, RuntimeError("option failure"))
        interaction.response.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
