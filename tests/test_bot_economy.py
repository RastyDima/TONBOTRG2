"""Bonus, reminder and history regressions; optional real PostgreSQL coverage."""
import os
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

_scratch = tempfile.TemporaryDirectory()
os.environ.update({
    "BOT_TOKEN": "offline-economy-tests", "RENDER": "false", "DATABASE_URL": "",
    "DATABASE_PATH": str(Path(_scratch.name) / "global.db"),
    "ADMIN_PANEL_PASSWORD": "offline-economy-tests", "WEBHOOK_SECRET": "offline-economy-tests",
})

import database  # noqa: E402
from database import Database, PostgresDatabase, TRANSACTION_FILTERS  # noqa: E402
from utils.economy_views import HISTORY_LABELS, bonus_status, bonuses_text, history_page  # noqa: E402
from utils.helpers import history_text  # noqa: E402
from utils.reminders import send_bonus_reminders  # noqa: E402


class EconomyDatabaseCases:
    def test_bonus_claims_credit_once_and_log_once(self):
        before = self.db.get_user(101)["balance"]
        for kind, amount in (("daily", 17), ("weekly", 29)):
            claim = getattr(self.db, f"claim_{kind}")
            self.assertTrue(claim(101, amount))
            self.assertFalse(claim(101, amount))
            self.assertFalse(claim(999, amount))
        self.assertEqual(self.db.get_user(101)["balance"], before + 46)
        self.assertEqual(self.db.count_transactions(101, category="bonuses"), 3)

    def test_preferences_persist_independently_and_do_not_block_claims(self):
        self.db.set_bonus_reminder(101, "daily", False)
        self.assertEqual(self.db.get_user(101)["daily_reminder_enabled"], 0)
        self.assertEqual(self.db.get_user(101)["weekly_reminder_enabled"], 1)
        self.assertTrue(self.db.claim_daily(101, 17))
        self.db.set_bonus_reminder(101, "weekly", False)
        self.db.init_db()
        self.assertEqual(self.db.get_user(101)["daily_reminder_enabled"], 0)
        self.assertEqual(self.db.get_user(101)["weekly_reminder_enabled"], 0)
        self.db.set_bonus_reminder(101, "daily", True)
        self.assertEqual(self.db.get_user(101)["daily_reminder_enabled"], 1)

    def test_eligibility_respects_flags_claims_and_delivery(self):
        with patch("database.date") as calendar:
            calendar.today.return_value = date(2026, 1, 4)
            self.db.claim_daily(101, 17)
            self.db.claim_weekly(101, 29)
        with patch("database.date") as calendar:
            calendar.today.return_value = date(2026, 1, 5)
            self.assertEqual(self.db.get_daily_eligible(), [{"id": 101}])
            self.assertEqual(self.db.get_weekly_eligible(), [{"id": 101}])
            self.db.set_bonus_reminder(101, "daily", False)
            self.assertEqual(self.db.get_daily_eligible(), [])
            self.assertEqual(self.db.get_weekly_eligible(), [{"id": 101}])
            self.db.mark_weekly_notified(101)
            self.assertEqual(self.db.get_weekly_eligible(), [])

    def test_history_filters_exclude_other_users(self):
        for kind in {kind for group in TRANSACTION_FILTERS.values() for kind in group}:
            self.db.add_balance(101, 1, kind, kind)
            self.db.add_balance(202, 1, kind, "another player")
        for category, kinds in TRANSACTION_FILTERS.items():
            rows = self.db.get_transactions(101, limit=100, category=category)
            self.assertTrue(all(row["user_id"] == 101 for row in rows))
            if kinds:
                self.assertTrue(all(row["type"] in kinds for row in rows))
            self.assertEqual(len(rows), self.db.count_transactions(101, category=category))
        self.assertEqual(set(HISTORY_LABELS), set(TRANSACTION_FILTERS))

    def test_history_pages_keep_snapshot_when_transactions_arrive(self):
        for number in range(24):
            self.db.add_balance(101, 1, "daily", f"operation {number}")
        first = history_page(self.db, 101)
        second = history_page(self.db, 101, page=1, anchor=first["anchor"])
        self.assertEqual(first["pages"], 3)
        self.db.add_balance(101, 99, "promo", "NEW TRANSACTION")
        self.assertEqual(second, history_page(self.db, 101, page=1, anchor=first["anchor"]))
        self.assertNotIn("NEW TRANSACTION", history_page(self.db, 101, page=2, anchor=first["anchor"])["text"])
        self.assertIn("NEW TRANSACTION", history_page(self.db, 101)["text"])
        first_ids = {row["id"] for row in self.db.get_transactions(101, before_id=first["anchor"])}
        second_ids = {row["id"] for row in self.db.get_transactions(101, offset=10, before_id=first["anchor"])}
        self.assertFalse(first_ids & second_ids)

    def test_empty_filter_and_out_of_range_page(self):
        empty = history_page(self.db, 101, "shop", 999)
        self.assertEqual((empty["page"], empty["pages"]), (0, 1))
        self.assertIn("Пока нет операций", empty["text"])
        self.assertNotIn("Пока нет операций", history_page(self.db, 101)["text"])

    def test_untrusted_filters_and_negative_pages_are_rejected(self):
        with self.assertRaises(ValueError):
            self.db.get_transactions(101, category="all'; DROP TABLE users; --")
        with self.assertRaises(ValueError):
            self.db.set_bonus_reminder(101, "is_admin", True)
        with self.assertRaises(ValueError):
            self.db.get_transactions(101, offset=-1)
        with self.assertRaises(ValueError):
            self.db.count_transactions(101, before_id=-1)
        self.assertIsNotNone(self.db.get_user(101))


class SQLiteEconomyTests(EconomyDatabaseCases, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.db"))
        self.db.register_user(101, None, "One")
        self.db.register_user(202, None, "Two")

    def tearDown(self):
        self.temp.cleanup()

    def test_migration_preserves_existing_balances_and_claims(self):
        path = str(Path(self.temp.name) / "legacy.db")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("""CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, balance INTEGER,
                is_blocked INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0, last_daily TEXT,
                created_at TEXT DEFAULT '2026-01-01')""")
            connection.execute("INSERT INTO users (id, balance, last_daily) VALUES (101, 777, '2026-01-02')")
        migrated = Database(path)
        self.assertEqual(migrated.get_user(101)["balance"], 777)
        self.assertEqual(migrated.get_user(101)["last_daily"], "2026-01-02")
        self.assertEqual(migrated.get_user(101)["daily_reminder_enabled"], 1)
        self.assertEqual(migrated.get_user(101)["weekly_reminder_enabled"], 1)

    def test_concurrent_bonus_claims_only_credit_once(self):
        for kind in ("daily", "weekly"):
            before = self.db.get_user(101)["balance"]
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(lambda _: getattr(self.db, f"claim_{kind}")(101, 53), range(8)))
            self.assertEqual(sum(results), 1)
            self.assertEqual(self.db.get_user(101)["balance"], before + 53)


@unittest.skipUnless(os.getenv("TEST_POSTGRES_URL"), "TEST_POSTGRES_URL is not configured")
class PostgresEconomyTests(EconomyDatabaseCases, unittest.TestCase):
    def setUp(self):
        import psycopg2
        import psycopg2.pool
        from psycopg2.extras import RealDictCursor
        self.patch = patch.multiple(database, psycopg2=psycopg2, RealDictCursor=RealDictCursor, create=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.admin = psycopg2.connect(os.environ["TEST_POSTGRES_URL"])
        self.admin.autocommit = True
        self.addCleanup(self.admin.close)
        self.schema = "economy_" + uuid.uuid4().hex
        with self.admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{self.schema}"')
        self.addCleanup(self.drop_schema)
        url = psycopg2.extensions.make_dsn(os.environ["TEST_POSTGRES_URL"], options=f"-c search_path={self.schema}")
        self.db = PostgresDatabase(url)
        self.addCleanup(self.db._pool.closeall)
        self.db.register_user(101, None, "One")
        self.db.register_user(202, None, "Two")

    def drop_schema(self):
        with self.admin.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA "{self.schema}" CASCADE')


class EconomyViewTests(unittest.TestCase):
    def test_week_boundary_and_next_bonus_dates(self):
        user = {"last_daily": "2026-01-04", "last_weekly": "2026-W01"}
        sunday = bonus_status(user, date(2026, 1, 4))
        self.assertFalse(sunday["daily"])
        self.assertFalse(sunday["weekly"])
        self.assertEqual(sunday["next_weekly"], "05.01.2026")
        monday = bonus_status(user, date(2026, 1, 5))
        self.assertTrue(monday["daily"])
        self.assertTrue(monday["weekly"])

    def test_both_bonus_amounts_appear_on_one_screen(self):
        text = bonuses_text({"balance": 50}, 17, 29)
        self.assertIn("Ежедневный — 17 TON", text)
        self.assertIn("Еженедельный — 29 TON", text)

    def test_history_escapes_descriptions_and_labels_and_distinguishes_refunds(self):
        text = history_text([
            {"amount": 5, "type": "<b>bad</b>", "description": "<script>&", "created_at": "<time>"},
            {"amount": 9, "type": "game_bet", "description": "refund", "created_at": "2026-01-01"},
        ])
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;&amp;", text)
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;", text)
        self.assertIn("Возврат ставки", text)


class ReminderDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_delivery_is_retried_and_disabled_weekly_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(str(Path(folder) / "test.db"))
            db.register_user(101, None, "One")
            with patch("database.date") as calendar:
                calendar.today.return_value = date(2026, 1, 4)
                db.claim_daily(101, 17)
                db.claim_weekly(101, 29)
            db.set_bonus_reminder(101, "weekly", False)
            with patch("database.date") as calendar:
                calendar.today.return_value = date(2026, 1, 5)
                send = AsyncMock(return_value=False)
                await send_bonus_reminders(db, send, 17, 29, lambda kind: kind)
                self.assertEqual(send.await_count, 1)
                self.assertEqual(db.get_user(101)["daily_notified"], 0)
                send.return_value = True
                await send_bonus_reminders(db, send, 17, 29, lambda kind: kind)
                self.assertEqual(db.get_user(101)["daily_notified"], 1)
                await send_bonus_reminders(db, send, 17, 29, lambda kind: kind)
                self.assertEqual(send.await_count, 2)

    async def test_opt_out_during_a_batch_is_respected(self):
        db = unittest.mock.Mock()
        db.get_daily_eligible.return_value = [{"id": 101}, {"id": 202}]
        db.get_weekly_eligible.return_value = []
        users = {101: {"id": 101, "is_blocked": 0, "daily_reminder_enabled": 1},
                 202: {"id": 202, "is_blocked": 0, "daily_reminder_enabled": 1}}
        db.get_user.side_effect = users.get
        async def deliver(*args):
            users[202]["daily_reminder_enabled"] = 0
            return True
        send = AsyncMock(side_effect=deliver)
        await send_bonus_reminders(db, send, 17, 29, lambda kind: kind)
        send.assert_awaited_once()
        db.mark_daily_notified.assert_called_once_with(101)


if __name__ == "__main__":
    unittest.main()
