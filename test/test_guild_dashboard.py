"""Unit tests for Server Dashboard and Guild Customization features."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from cogs.command_support import CommandDisabledError
from db import Database, GuildSettings
from main import create_bot, error_message
from web.app import create_app
from web.discord_api import is_admin_or_owner, filter_admin_guilds


class GuildDashboardDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database("sqlite:///:memory:")

    def test_default_guild_settings_returns_r_prefix_and_empty_disabled_lists(self):
        settings = self.db.get_guild_settings("guild-1")
        self.assertEqual(settings["guild_id"], "guild-1")
        self.assertEqual(settings["prefix"], "r.")
        self.assertEqual(settings["disabled_commands"], [])
        self.assertEqual(settings["disabled_categories"], [])
        self.assertIsNone(settings["mod_log_channel_id"])
        self.assertIsNone(settings["welcome_channel_id"])
        self.assertIsNone(settings["welcome_message"])

    def test_update_guild_settings_persists_changes(self):
        self.db.update_guild_settings(
            "guild-1",
            prefix="!",
            disabled_commands=["rob", "blackjack"],
            disabled_categories=["jogos"],
            mod_log_channel_id="999",
            welcome_channel_id="888",
            welcome_message="Bem-vindo {user}!",
        )

        settings = self.db.get_guild_settings("guild-1")
        self.assertEqual(settings["prefix"], "!")
        self.assertEqual(set(settings["disabled_commands"]), {"rob", "blackjack"})
        self.assertEqual(settings["disabled_categories"], ["jogos"])
        self.assertEqual(settings["mod_log_channel_id"], "999")
        self.assertEqual(settings["welcome_channel_id"], "888")
        self.assertEqual(settings["welcome_message"], "Bem-vindo {user}!")

        # Helper lookups
        self.assertEqual(self.db.get_guild_prefix("guild-1"), "!")
        self.assertTrue(self.db.is_command_disabled("guild-1", "rob"))
        self.assertTrue(self.db.is_command_disabled("guild-1", "blackjack"))
        self.assertFalse(self.db.is_command_disabled("guild-1", "work"))
        self.assertTrue(self.db.is_command_disabled("guild-1", "any_game", category_key="jogos"))

    def test_confessions_and_tickets_and_quiz_config_lookups(self):
        self.db.configure_confessions("guild-1", "111", "222")
        confession = self.db.get_confession_config("guild-1")
        self.assertEqual(confession["channel_id"], "111")
        self.assertEqual(confession["log_channel_id"], "222")
        self.assertEqual(confession["next_number"], 1)

        self.db.configure_tickets("guild-1", "333")
        ticket = self.db.get_ticket_config("guild-1")
        self.assertEqual(ticket["category_id"], "333")
        self.assertEqual(ticket["next_number"], 1)

        self.db.configure_quiz("guild-1", "444", "555", 250, 1000)
        quiz = self.db.get_quiz_config("guild-1")
        self.assertEqual(quiz["channel_id"], "444")
        self.assertEqual(quiz["review_channel_id"], "555")
        self.assertEqual(quiz["reward"], 250)
        self.assertEqual(quiz["enabled"], 1)


class BotGuildCustomizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = create_bot()

    def test_bot_command_prefix_attribute_is_r_dot(self):
        # Keeps compatibility with legacy test assertions
        self.assertEqual(self.bot.command_prefix, "r.")

    async def test_dynamic_get_prefix_resolves_guild_custom_prefix(self):
        with patch("main.database.get_guild_prefix", return_value="!"):
            msg = SimpleNamespace(guild=SimpleNamespace(id=12345))
            prefixes = await self.bot.get_prefix(msg)
            self.assertIn("!", prefixes)
            self.assertIn("r.", prefixes)

    async def test_dynamic_get_prefix_returns_default_when_no_guild_or_default_prefix(self):
        with patch("main.database.get_guild_prefix", return_value="r."):
            msg = SimpleNamespace(guild=SimpleNamespace(id=12345))
            prefix = await self.bot.get_prefix(msg)
            self.assertEqual(prefix, "r.")

        dm_msg = SimpleNamespace(guild=None)
        prefix = await self.bot.get_prefix(dm_msg)
        self.assertEqual(prefix, "r.")

    def test_error_message_handles_command_disabled_error(self):
        err = CommandDisabledError("rob")
        msg = error_message(err, "r.rob")
        self.assertIn("rob", msg)
        self.assertIn("desativado", msg)

    async def test_bot_check_blocks_disabled_command(self):
        check = self.bot._checks[0]
        cmd = self.bot.get_command("rob")
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id="guild-blocked"),
            command=cmd,
        )

        with patch("main.database.is_command_disabled", return_value=True):
            with self.assertRaises(CommandDisabledError):
                await check(ctx)

    async def test_bot_check_allows_protected_commands_even_if_reported_disabled(self):
        check = self.bot._checks[0]
        cmd = self.bot.get_command("help")
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id="guild-blocked"),
            command=cmd,
        )

        with patch("main.database.is_command_disabled", return_value=True):
            result = await check(ctx)
            self.assertTrue(result)

    async def test_bot_check_passes_category_key(self):
        check = self.bot._checks[0]
        cmd = self.bot.get_command("rob")
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id="guild-cat-blocked"),
            command=cmd,
        )

        with patch("main.database.is_command_disabled") as mock_disabled:
            mock_disabled.return_value = True
            with self.assertRaises(CommandDisabledError):
                await check(ctx)
            mock_disabled.assert_called_with("guild-cat-blocked", "rob", category_key="economia")


class DiscordPermissionsAndWebDashboardTests(unittest.TestCase):
    def test_is_admin_or_owner_detection(self):
        # Owner check
        self.assertTrue(is_admin_or_owner({"id": "1", "owner": True, "permissions": "0"}))
        # Administrator flag (0x8) check
        self.assertTrue(is_admin_or_owner({"id": "2", "owner": False, "permissions": "8"}))
        self.assertTrue(is_admin_or_owner({"id": "3", "owner": False, "permissions": "2147483647"}))
        # Regular member without admin
        self.assertFalse(is_admin_or_owner({"id": "4", "owner": False, "permissions": "104324673"}))
        self.assertFalse(is_admin_or_owner({"id": "5", "owner": False, "permissions": "0"}))

    def test_filter_admin_guilds(self):
        guilds = [
            {"id": "1", "name": "Owner Server", "owner": True, "permissions": "0"},
            {"id": "2", "name": "Admin Server", "owner": False, "permissions": "8"},
            {"id": "3", "name": "Regular Member Server", "owner": False, "permissions": "0"},
        ]
        filtered = filter_admin_guilds(guilds)
        self.assertEqual(len(filtered), 2)
        self.assertEqual({g["id"] for g in filtered}, {"1", "2"})

    def test_dashboard_routes_and_api(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()

        # 1. Homepage
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"RalseiBot", res.data)

        # 2. Login redirect without session
        res = client.get("/dashboard")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login", res.headers["Location"])

        # 3. Dev login bypass
        res = client.get("/dev-login", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Selecione um Servidor", res.data)

        # 4. Save settings API
        with patch("web.routes.user_can_manage_guild", return_value=True), \
             patch("web.routes.database.update_guild_settings", return_value={"prefix": "!"}) as mock_save:
            res = client.post(
                "/api/guild/123/settings",
                json={"prefix": "!", "disabled_commands": ["rob"]},
            )
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data["success"])
            mock_save.assert_called_once()

        # 5. Reset prefix API
        with patch("web.routes.user_can_manage_guild", return_value=True), \
             patch("web.routes.database.update_guild_settings") as mock_save:
            res = client.post("/api/guild/123/reset-prefix")
            self.assertEqual(res.status_code, 200)
            mock_save.assert_called_with("123", prefix="r.")

    def test_guild_view_renders_tabs_and_switch_script(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()

        with client.session_transaction() as sess:
            sess["user"] = {"id": "123", "username": "admin"}

        with patch("web.routes.user_can_manage_guild", return_value=True), \
             patch("web.routes.discord_api.get_bot_guild_ids", return_value={"123"}), \
             patch("web.routes.discord_api.get_guild_channels", return_value={"text_channels": [], "categories": []}):
            res = client.get("/guild/123")
            self.assertEqual(res.status_code, 200)
            html = res.data.decode("utf-8")
            self.assertIn("switchTab('tab-general')", html)
            self.assertIn("switchTab('tab-commands')", html)
            self.assertIn("switchTab('tab-confessions')", html)
            self.assertIn("switchTab('tab-tickets')", html)
            self.assertIn("switchTab('tab-quiz')", html)
            self.assertIn("window.switchTab = function", html)
            self.assertIn("window.filterCategory = function", html)

    def test_vercel_serverless_entrypoint_and_config(self):
        # Verify api.index exports a valid WSGI Flask app
        from api.index import app as vercel_app
        client = vercel_app.test_client()

        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"RalseiBot", res.data)

        # Verify static files served correctly
        res_css = client.get("/static/css/style.css")
        self.assertEqual(res_css.status_code, 200)
        self.assertIn(b"--ralsei-mint", res_css.data)

        # Verify Vercel redirect URI resolution
        with patch.dict("os.environ", {"VERCEL": "1", "VERCEL_PROJECT_PRODUCTION_URL": "ralseibot.vercel.app"}):
            import importlib
            import web.config as w_conf
            importlib.reload(w_conf)
            self.assertEqual(w_conf.DISCORD_REDIRECT_URI, "https://ralseibot.vercel.app/callback")
            self.assertTrue(w_conf.IS_VERCEL)


if __name__ == "__main__":
    unittest.main()

