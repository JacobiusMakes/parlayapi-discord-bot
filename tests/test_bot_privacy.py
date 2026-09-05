"""Offline access/privacy checks against real discord.py command callbacks."""
import os
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
OWNER = 123456789012345678
with patch.dict(os.environ, {
    "PARLAY_BOT_OWNER_ID": str(OWNER),
    "DISCORD_TOKEN": "offline-test-token",
    "PARLAY_API_KEY": "offline-test-key",
}):
    import bot as app


def interaction(user_id=OWNER, channel_id=10, done=False):
    state = {"done": done}

    async def mark_done(*args, **kwargs):
        state["done"] = True

    return SimpleNamespace(
        user=SimpleNamespace(
            id=user_id, guild_permissions=SimpleNamespace(administrator=True)),
        channel_id=channel_id,
        response=SimpleNamespace(
            is_done=Mock(side_effect=lambda: state["done"]),
            defer=AsyncMock(side_effect=mark_done),
            send_message=AsyncMock(side_effect=mark_done)),
        followup=SimpleNamespace(send=AsyncMock()),
    )


class OwnerConfigurationTests(unittest.TestCase):
    def test_numeric_snowflake_bounds(self):
        self.assertEqual(app.parse_owner_id(" %s " % OWNER), OWNER)
        self.assertEqual(app.parse_owner_id(str((1 << 64) - 1)), (1 << 64) - 1)

    def test_missing_or_malformed_owner_stops_before_discord_initialization(self):
        invalid = (None, "", " ", "0", "-1", "+123", "0123", "owner", "1.0",
                   "123 456", "１２３", "١٢٣", str(1 << 64), "9" * 100)
        for raw in invalid:
            with self.subTest(raw=raw):
                env = {} if raw is None else {"PARLAY_BOT_OWNER_ID": raw}
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(app.discord.Client, "__init__") as initialize:
                    with self.assertRaisesRegex(ValueError, "PARLAY_BOT_OWNER_ID"):
                        app.OddsBot()
                    initialize.assert_not_called()

    def test_owner_gate_is_installed_on_real_command_tree(self):
        self.assertIsInstance(app.bot.tree, app.OwnerCommandTree)
        self.assertEqual(app.bot.owner_id, OWNER)
        self.assertEqual({c.name for c in app.bot.tree.get_commands()},
                         {"odds", "line", "moves", "parlaycheck"})

    def test_missing_discord_token_never_connects(self):
        with patch.object(app, "DISCORD_TOKEN", None), patch.object(app.bot, "run") as run:
            with self.assertRaisesRegex(SystemExit, "DISCORD_TOKEN"):
                app.main()
            run.assert_not_called()

    def test_fresh_process_import_fails_closed_without_owner(self):
        for raw in (None, "not-a-user-id"):
            env = os.environ.copy()
            env.pop("PARLAY_BOT_OWNER_ID", None)
            env["DISCORD_TOKEN"] = "offline-test-token"
            env["PARLAY_API_KEY"] = "offline-test-key"
            if raw is not None:
                env["PARLAY_BOT_OWNER_ID"] = raw
            result = subprocess.run(
                [sys.executable, "-c", "import bot"],
                cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PARLAY_BOT_OWNER_ID", result.stderr)
            self.assertNotIn("offline-test-token", result.stderr + result.stdout)
            self.assertNotIn("offline-test-key", result.stderr + result.stdout)


class PrivateCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Any accidental actual HTTP attempt fails this test immediately.
        self.network = patch.object(app.oddscore, "api_get",
                                    side_effect=AssertionError("Network forbidden in tests"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.discord_network = patch.object(
            app.bot.http, "request", new_callable=AsyncMock,
            side_effect=AssertionError("Discord network forbidden in tests"))
        self.discord_network.start()
        self.addCleanup(self.discord_network.stop)

    def assert_private(self, it, replies=1):
        calls = it.response.send_message.call_args_list + it.followup.send.call_args_list
        self.assertEqual(len(calls), replies)
        for call in calls + it.response.defer.call_args_list:
            self.assertIs(call.kwargs.get("ephemeral"), True)

    async def test_tree_rejects_nonowner_even_if_server_administrator(self):
        it = interaction(OWNER + 1)
        self.assertFalse(await app.bot.tree.interaction_check(it))
        self.assert_private(it)
        self.assertTrue(await app.bot.tree.interaction_check(interaction()))

    async def test_every_callback_rejects_nonowner_before_provider_or_warm_cache(self):
        cases = ((app.odds, ("team",)), (app.line, ("team",)),
                 (app.moves, ()), (app.parlaycheck, ("-110,-110",)))
        for command, args in cases:
            with self.subTest(command=command.name):
                it = interaction(OWNER + 1)
                with patch.object(app.oddscore, "_cache_get", return_value="private cache") as cache, \
                        patch.object(app, "_fetch_odds", new_callable=AsyncMock) as fetch, \
                        patch.object(app.oddscore, "fetch_movers") as movers, \
                        patch.object(app.oddscore, "parse_american_prices") as math:
                    await command.callback(it, *args)
                    cache.assert_not_called()
                    fetch.assert_not_awaited()
                    movers.assert_not_called()
                    math.assert_not_called()
                it.response.defer.assert_not_awaited()
                self.assert_private(it)

    async def test_event_helper_also_rejects_nonowner(self):
        it = interaction(OWNER + 1, done=True)
        with patch.object(app, "_fetch_odds", new_callable=AsyncMock) as fetch:
            await app._reply_events(it, "baseball_mlb", "", "h2h", Mock())
            fetch.assert_not_awaited()
        self.assert_private(it)

    async def test_owner_odds_and_line_success_are_private(self):
        # No source odds copied into the fixture; exercises the successful event path.
        events = [{"home_team": "Fixture Home", "away_team": "Fixture Away", "bookmakers": []}]
        for command in (app.odds, app.line):
            with self.subTest(command=command.name):
                it = interaction()
                with patch.object(app.oddscore, "fetch_odds", return_value=(events, None)) as fetch:
                    await command.callback(it, "fixture")
                    fetch.assert_called_once()
                it.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
                self.assert_private(it)
                self.assertIn("embeds", it.followup.send.call_args.kwargs)

    async def test_owner_empty_result_is_private(self):
        it = interaction()
        with patch.object(app.oddscore, "fetch_odds", return_value=([], None)):
            await app.odds.callback(it, "missing")
        self.assert_private(it)

    async def test_odds_api_errors_are_private(self):
        for command in (app.odds, app.line):
            with self.subTest(command=command.name):
                it = interaction()
                with patch.object(app.oddscore, "fetch_odds", side_effect=app.oddscore.ApiError("offline error")):
                    await command.callback(it, "team")
                self.assert_private(it)

    async def test_owner_moves_success_empty_and_error_are_private(self):
        fixtures = ([], [{"home_team": "Fixture Home", "away_team": "Fixture Away"}])
        for movers in fixtures:
            it = interaction()
            with patch.object(app.oddscore, "fetch_movers", return_value=movers) as fetch:
                await app.moves.callback(it)
                fetch.assert_called_once()
            self.assert_private(it)
        it = interaction()
        with patch.object(app.oddscore, "fetch_movers", side_effect=app.oddscore.ApiError("offline error")):
            await app.moves.callback(it)
        self.assert_private(it)

    async def test_owner_math_success_and_invalid_input_are_private(self):
        for prices in ("-110,-110", "not a price"):
            it = interaction()
            await app.parlaycheck.callback(it, prices)
            self.assert_private(it)

    async def test_cooldown_before_and_after_defer_is_private(self):
        error = app.app_commands.CommandOnCooldown(app.app_commands.Cooldown(1, 15), 5)
        for done in (False, True):
            it = interaction(done=done)
            await app.on_app_command_error(it, error)
            self.assert_private(it)
        self.assertEqual(app.cooldown_key(interaction(channel_id=10)),
                         app.cooldown_key(interaction(channel_id=20)))

    async def test_unexpected_error_before_and_after_defer_is_private(self):
        for done in (False, True):
            it = interaction(done=done)
            with patch.object(app.log, "exception"):
                await app.on_app_command_error(it, app.app_commands.AppCommandError("offline"))
            self.assert_private(it)

    async def test_private_helper_cannot_be_overridden_to_public(self):
        it = interaction(done=True)
        await app._private_reply(it, "fixture", ephemeral=False)
        self.assert_private(it)


if __name__ == "__main__":
    unittest.main()
