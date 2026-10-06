"""Player settings, GIF persistence, rankings and atomic coinflip regressions."""
import asyncio
import csv
import io
import os
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

_scratch = tempfile.TemporaryDirectory()
os.environ.setdefault("BOT_TOKEN", "offline-player-tests")
os.environ.setdefault("RENDER", "false")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("DATABASE_PATH", str(Path(_scratch.name) / "global.db"))
os.environ.setdefault("ADMIN_PANEL_PASSWORD", "offline-player-tests")
os.environ.setdefault("WEBHOOK_SECRET", "offline-player-tests")

from database import Database, PostgresDatabase
from tests.test_avatars import GIF
from utils.avatar_uploads import validate_avatar
from utils.player_views import history_csv


class PlayerDatabaseCases:
    def test_preferences_and_favorites_persist_without_changing_other_users(self):
        self.db.set_player_preferences(101, {"bio": "Привет <b>мир</b>", "theme": "light", "saved_bet": 250, "hide_stats": True})
        self.db.set_favorite(101, "mines", True)
        self.db.set_favorite(101, "mines", True)
        self.db.init_db()
        prefs = self.db.get_player_preferences(101)
        self.assertEqual(prefs["favorites"], ["mines"])
        self.assertEqual(prefs["bio"], "Привет <b>мир</b>")
        self.assertEqual(prefs["saved_bet"], 250)
        self.assertTrue(prefs["hide_stats"])
        self.assertFalse(self.db.get_player_preferences(202)["hide_stats"])
        self.db.set_favorite(101, "mines", False)
        self.assertEqual(self.db.get_player_preferences(101)["favorites"], [])

    def test_invalid_settings_cannot_modify_account_columns(self):
        for values in ({"is_admin": True}, {"theme": "invalid"}, {"hide_stats": 1},
                       {"saved_bet": True}, {"saved_bet": 0}, {"bio": "x" * 201}):
            with self.assertRaises(ValueError):
                self.db.set_player_preferences(101, values)
        with self.assertRaises(ValueError):
            self.db.set_favorite(101, "mines; DROP TABLE users", True)
        self.assertEqual(self.db.get_user(101)["is_admin"], 0)

    def test_gif_persists_and_is_private_to_owner(self):
        self.assertEqual(validate_avatar(GIF), "image/gif")
        self.db.set_custom_avatar(101, GIF, "image/gif")
        self.db.init_db()
        self.assertEqual(self.db.get_custom_avatar(101)["data"], GIF)
        self.assertIsNone(self.db.get_custom_avatar(202))
        self.assertTrue(self.db.get_player_preferences(101)["custom_avatar"])
        self.db.delete_custom_avatar(101)
        self.assertIsNone(self.db.get_custom_avatar(101))

    def test_coinflip_retry_does_not_repeat_stake_payout_stats_or_xp(self):
        before = self.db.get_user(101)["balance"]
        original = self.db.play_coinflip(101, "a" * 32, 100, "орёл", "орёл")
        replay = self.db.play_coinflip(101, "a" * 32, 100, "орёл", "решка")
        self.assertTrue(original["fresh"])
        self.assertFalse(replay["fresh"])
        self.assertEqual(replay["result"], "орёл")
        user = self.db.get_user(101)
        self.assertEqual(user["balance"], before + 85)
        self.assertEqual(user["xp"], 15)
        self.assertEqual(self.db.get_stats(101)["total_games"], 1)
        self.assertEqual(len(self.db.get_transactions(101, category="games")), 2)
        conflict = self.db.play_coinflip(101, "a" * 32, 200, "орёл", "орёл")
        self.assertEqual(conflict["error"], "round conflict")

    def test_concurrent_retries_commit_one_round(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: self.db.play_coinflip(101, "b" * 32, 100, "орёл", "решка"), range(6)))
        self.assertEqual(sum(result["fresh"] for result in results), 1)
        self.assertEqual(self.db.get_user(101)["balance"], 900)
        self.assertEqual(self.db.get_stats(101)["total_games"], 1)

    def test_concurrent_rounds_cannot_overdraw_balance(self):
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda index: self.db.play_coinflip(101, format(index, "032x"), 300, "орёл", "решка"), range(6)))
        self.assertEqual(sum("error" not in result for result in results), 3)
        self.assertEqual(self.db.get_user(101)["balance"], 100)
        self.assertEqual(self.db.get_stats(101)["losses"], 3)

    def test_coinflip_excludes_active_mines_and_uses_account_scoped_ids(self):
        from games.mines import MinesGame
        self.db.play_coinflip(101, "a" * 32, 100, "орёл", "орёл")
        game = MinesGame(101, 100, 3)
        self.assertTrue(self.db.start_mines_round(game))
        before = self.db.get_user(101)["balance"]
        self.assertEqual(self.db.play_coinflip(101, "b" * 32, 100, "орёл", "орёл")["error"], "active game")
        self.assertFalse(self.db.play_coinflip(101, "a" * 32, 100, "орёл", "решка")["fresh"])
        self.assertEqual(self.db.get_user(101)["balance"], before)
        self.assertTrue(self.db.play_coinflip(202, "a" * 32, 100, "орёл", "решка")["fresh"])
        self.assertEqual(self.db.get_user(202)["balance"], 900)

    def test_invalid_coinflip_inputs_cannot_spend(self):
        for request_id, bet, choice in (("bad", 100, "орёл"), ("a" * 32, True, "орёл"), ("a" * 32, -1, "орёл"), ("a" * 32, 100, "invalid")):
            with self.assertRaises(ValueError):
                self.db.play_coinflip(101, request_id, bet, choice, "орёл")
        self.assertEqual(self.db.get_user(101)["balance"], 1000)

    def test_statistics_keep_refunds_out_of_game_results(self):
        self.db.play_coinflip(101, "a" * 32, 100, "орёл", "орёл")
        self.db.add_game(101, "mines", 400, 400, "cancel")
        self.db.add_balance(101, 20, "daily", "Бонус")
        data = self.db.player_statistics(101, 7)
        self.assertEqual(data["summary"]["games"], 1)
        self.assertEqual(data["summary"]["net"], 85)
        self.assertEqual(len(data["points"]), 8)
        self.assertEqual(data["points"][-1]["balance"], self.db.get_user(101)["balance"])
        self.assertEqual(data["points"][-1]["balance"] - data["points"][0]["balance"], 1105)

    def test_hidden_and_blocked_users_do_not_appear_in_rankings(self):
        self.db.add_xp(101, 500)
        self.db.add_xp(202, 100)
        self.db.set_player_preferences(101, {"hide_stats": True})
        data = self.db.player_leaderboard(101, "xp")
        self.assertIsNone(data["my_rank"])
        self.assertEqual([row["id"] for row in data["players"]], [202])
        self.db.set_blocked(202, True)
        self.assertEqual(self.db.player_leaderboard(101, "xp")["players"], [])

    def test_own_rank_is_returned_beyond_first_page_and_ties_are_stable(self):
        for user_id in range(1000, 1060):
            self.db.register_user(user_id, None, "Other")
            self.db.add_xp(user_id, 10)
        self.db.add_xp(101, 1)
        data = self.db.player_leaderboard(101, "xp", "all", 20)
        self.assertEqual(data["my_rank"], 61)
        self.assertEqual([row["id"] for row in data["players"]], list(range(1000, 1020)))

    def test_period_ranking_ignores_old_games(self):
        self.db.add_game(101, "coinflip", 100, 185, "win")
        with self.db._player_cursor() as cur:
            cur.execute(self.db._player_sql("UPDATE games SET created_at = '2020-01-01 00:00:00' WHERE user_id = ?"), (101,))
        self.db.add_game(202, "coinflip", 100, 185, "win")
        data = self.db.player_leaderboard(101, "wins", "week")
        self.assertEqual([row["id"] for row in data["players"]], [202])
        self.assertEqual(len(self.db.player_leaderboard(101, "wins", "all")["players"]), 2)

    def test_csv_contains_only_owner_and_escapes_spreadsheet_formulas(self):
        self.db.add_balance(101, 1, "daily", "=CMD()")
        self.db.add_balance(202, 2, "daily", "Other private record")
        text = history_csv(self.db, 101).decode("utf-8-sig")
        self.assertNotIn("Other private record", text)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1][3], "'=CMD()")


class SQLitePlayerTests(PlayerDatabaseCases, unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Database(str(Path(self.folder.name) / "test.db"))
        self.db.register_user(101, None, "One")
        self.db.register_user(202, None, "Two")


@unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "TEST_POSTGRES_URL is not configured")
class PostgreSQLPlayerTests(PlayerDatabaseCases, unittest.TestCase):
    def setUp(self):
        import psycopg2
        from psycopg2.extensions import make_dsn
        self.admin = psycopg2.connect(os.environ["TEST_POSTGRES_URL"])
        self.admin.autocommit = True
        self.addCleanup(self.admin.close)
        schema = "player_" + uuid.uuid4().hex
        with self.admin.cursor() as cur:
            cur.execute('CREATE SCHEMA "' + schema + '"')
        def drop():
            with self.admin.cursor() as cur:
                cur.execute('DROP SCHEMA "' + schema + '" CASCADE')
        self.addCleanup(drop)
        self.db = PostgresDatabase(make_dsn(os.environ["TEST_POSTGRES_URL"], options="-csearch_path=" + schema))
        self.addCleanup(self.db._pool.closeall)
        self.db.register_user(101, None, "One")
        self.db.register_user(202, None, "Two")


class ImageValidationTests(unittest.TestCase):
    def test_invalid_and_oversized_gif_rejected_before_storage(self):
        for data in (b"GIF89a-invalid", b"<svg/>", GIF + b"0" * (2 * 1024 * 1024)):
            with self.assertRaises(ValueError):
                validate_avatar(data)

    def test_overlong_animation_rejected(self):
        from PIL import Image
        frames = [Image.new("RGB", (2, 2), "red" if index % 2 else "blue") for index in range(121)]
        buffer = io.BytesIO()
        frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=20)
        with self.assertRaises(ValueError):
            validate_avatar(buffer.getvalue())
