import os
import json
import sqlite3
import secrets
import time
from contextlib import closing, contextmanager
from datetime import date

from config import ADMIN_IDS, DATABASE_PATH, DATABASE_URL, STARTING_BALANCE


TRANSACTION_FILTERS = {
    "all": (),
    "games": ("game_bet", "game_win"),
    "bonuses": ("bonus", "daily", "weekly", "promo"),
    "transfers": ("transfer_in", "transfer_out"),
    "shop": ("shop",),
    "referrals": ("referral",),
}


def _transaction_where(user_id, category, before_id, placeholder):
    if category not in TRANSACTION_FILTERS:
        raise ValueError("Unknown transaction filter")
    clauses = [f"user_id = {placeholder}"]
    params = [user_id]
    types = TRANSACTION_FILTERS[category]
    if types:
        clauses.append(f"type IN ({', '.join([placeholder] * len(types))})")
        params.extend(types)
    if before_id is not None:
        if before_id < 0:
            raise ValueError("Invalid history snapshot")
        clauses.append(f"id <= {placeholder}")
        params.append(before_id)
    return " AND ".join(clauses), tuple(params)


class _MinesConflict(Exception):
    """Rollback a stake when the player already has a stored Mines round."""

if DATABASE_URL:
    import psycopg2
    import psycopg2.pool
    from psycopg2.extras import RealDictCursor


def current_week() -> str:
    """Идентификатор текущей недели в формате 'YYYY-Www'."""
    iso = date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _calc_level(xp: int) -> int:
    """Уровень по XP: level = floor(sqrt(xp / 50))."""
    import math
    return int(math.sqrt(xp / 50)) + 1 if xp >= 0 else 1


def xp_for_level(level: int) -> int:
    """Минимальный XP для достижения уровня."""
    return ((level - 1) ** 2) * 50


def level_info(xp: int) -> dict:
    """Возвращает полную информацию об уровне."""
    level = _calc_level(xp)
    current_level_xp = xp_for_level(level)
    next_level_xp = xp_for_level(level + 1)
    progress = (xp - current_level_xp) / max(1, next_level_xp - current_level_xp)
    return {
        "level": level,
        "xp": xp,
        "current_level_xp": current_level_xp,
        "next_level_xp": next_level_xp,
        "progress": min(progress, 1.0),
    }


LEVEL_NAMES = {
    1: "Новичок",
    5: "Игрок",
    10: "Боец",
    15: "Мастер",
    20: "Легенда",
    30: "Бог",
}


def level_name(level: int) -> str:
    name = "Новичок"
    for threshold, n in sorted(LEVEL_NAMES.items()):
        if level >= threshold:
            name = n
    return name


class Database:
    """Слой работы с SQLite (локальная разработка без Postgres)."""

    def __init__(self, path: str = DATABASE_PATH):
        self.path = path
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    balance INTEGER NOT NULL DEFAULT 0,
                    rubies REAL NOT NULL DEFAULT 0,
                    is_blocked INTEGER NOT NULL DEFAULT 0,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    last_daily TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    user_id INTEGER PRIMARY KEY,
                    total_games INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    total_bet INTEGER NOT NULL DEFAULT 0,
                    total_won INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    game_type TEXT NOT NULL,
                    bet INTEGER NOT NULL,
                    win_amount INTEGER NOT NULL DEFAULT 0,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS active_mines (
                    user_id INTEGER PRIMARY KEY,
                    round_id TEXT NOT NULL UNIQUE,
                    bet INTEGER NOT NULL,
                    mine_count INTEGER NOT NULL,
                    seed TEXT NOT NULL,
                    house_edge REAL NOT NULL,
                    revealed TEXT NOT NULL DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS promos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    amount INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS promo_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    promo_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(promo_id, user_id)
                )
            """)
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
            if "daily_notified" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN daily_notified INTEGER NOT NULL DEFAULT 0")
            if "last_weekly" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN last_weekly TEXT")
            if "weekly_notified" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN weekly_notified INTEGER NOT NULL DEFAULT 0")
            for kind in ("daily", "weekly"):
                if f"{kind}_reminder_enabled" not in cols:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {kind}_reminder_enabled INTEGER NOT NULL DEFAULT 1")
            conn.execute("CREATE INDEX IF NOT EXISTS transactions_user_id_idx ON transactions (user_id, id)")
            if "max_balance" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN max_balance INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE users SET max_balance = balance WHERE max_balance = 0")
            if "referrer_id" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
            if "referral_count" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN referral_count INTEGER NOT NULL DEFAULT 0")
            if "referral_earned" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN referral_earned INTEGER NOT NULL DEFAULT 0")
            if "active_frame" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN active_frame TEXT")
            if "active_title" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN active_title TEXT")
            if "xp" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN xp INTEGER NOT NULL DEFAULT 0")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    purchased_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(user_id, item_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id INTEGER NOT NULL,
                    achievement_id TEXT NOT NULL,
                    earned_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (user_id, achievement_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_showcase (
                    user_id INTEGER NOT NULL,
                    achievement_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (user_id, achievement_id),
                    UNIQUE (user_id, position)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mobile_sessions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    device_label TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS mobile_sessions_user_idx ON mobile_sessions(user_id)")
            conn.commit()

    def create_mobile_session(self, user_id: int, device_label: str, expires_at: int) -> str:
        session_id = secrets.token_urlsafe(24)
        now = int(time.time())
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM mobile_sessions WHERE expires_at <= ?", (now,))
            conn.execute("""
                INSERT INTO mobile_sessions
                    (id, user_id, device_label, created_at, last_seen_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, user_id, device_label, now, now, expires_at))
        return session_id

    def get_mobile_session(self, session_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM mobile_sessions WHERE id = ?", (session_id,)).fetchone()
            return dict(row) if row else None

    def touch_mobile_session(self, session_id: str, now: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("""
                UPDATE mobile_sessions SET last_seen_at = ?
                WHERE id = ? AND last_seen_at <= ? AND revoked_at IS NULL
            """, (now, session_id, now - 300))

    def list_mobile_sessions(self, user_id: int) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("""
                SELECT id, device_label, created_at, last_seen_at, expires_at
                FROM mobile_sessions
                WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?
                ORDER BY last_seen_at DESC, created_at DESC
            """, (user_id, int(time.time()))).fetchall()
            return [dict(row) for row in rows]

    def revoke_mobile_session(self, user_id: int, session_id: str) -> bool:
        with closing(self._connect()) as conn, conn:
            result = conn.execute("""
                UPDATE mobile_sessions SET revoked_at = ?
                WHERE user_id = ? AND id = ? AND revoked_at IS NULL
            """, (int(time.time()), user_id, session_id))
            return result.rowcount > 0

    def revoke_other_mobile_sessions(self, user_id: int, current_id: str | None) -> int:
        with closing(self._connect()) as conn, conn:
            result = conn.execute("""
                UPDATE mobile_sessions SET revoked_at = ?
                WHERE user_id = ? AND id <> ? AND revoked_at IS NULL
                  AND expires_at > ?
            """, (int(time.time()), user_id, current_id or "", int(time.time())))
            return result.rowcount

    # ---------- Пользователи ----------

    def register_user(self, user_id: int, username, first_name, referrer_id: int | None = None) -> None:
        is_admin = 1 if user_id in ADMIN_IDS else 0
        with closing(self._connect()) as conn, conn:
            new = conn.execute(
                "SELECT 1 FROM users WHERE id = ?", (user_id,)
            ).fetchone() is None
            conn.execute(
                """
                INSERT INTO users (id, username, first_name, balance, is_admin, last_daily, referrer_id)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (user_id, username, first_name, STARTING_BALANCE, is_admin, referrer_id),
            )
            conn.execute("INSERT OR IGNORE INTO stats (user_id) VALUES (?)", (user_id,))
            if new:
                conn.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (user_id, STARTING_BALANCE, "bonus", "Приветственный бонус"),
                )
                if referrer_id and referrer_id != user_id:
                    ref = conn.execute("SELECT 1 FROM users WHERE id = ?", (referrer_id,)).fetchone()
                    if ref:
                        conn.execute(
                            "UPDATE users SET referral_count = referral_count + 1 WHERE id = ?",
                            (referrer_id,),
                        )

    def add_referral_earning(self, user_id: int, amount: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET referral_earned = referral_earned + ? WHERE id = ?",
                (amount, user_id),
            )

    def get_user(self, user_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        username = (username or "").lstrip("@").lower()
        if not username:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(username) = ? LIMIT 1", (username,)
            ).fetchone()
            return dict(row) if row else None

    def search_users(self, query: str, limit: int = 50) -> list[dict]:
        """Поиск игроков по ID, имени или username (для веб-админки)."""
        query = (query or "").strip().lstrip("@")
        with closing(self._connect()) as conn:
            if not query:
                rows = conn.execute(
                    "SELECT * FROM users ORDER BY balance DESC LIMIT ?", (limit,)
                ).fetchall()
            elif query.isdigit():
                row = conn.execute(
                    "SELECT * FROM users WHERE id = ? LIMIT 1", (int(query),)
                ).fetchone()
                rows = [row] if row else []
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM users
                    WHERE lower(username) LIKE ? OR lower(first_name) LIKE ?
                    ORDER BY balance DESC LIMIT ?
                    """,
                    (f"%{query.lower()}%", f"%{query.lower()}%", limit),
                ).fetchall()
            return [dict(r) for r in rows]

    def is_user_blocked(self, user_id: int) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT is_blocked FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return bool(row and row["is_blocked"])

    def set_blocked(self, user_id: int, blocked: bool) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET is_blocked = ? WHERE id = ?",
                (1 if blocked else 0, user_id),
            )

    def add_balance(self, user_id: int, amount: int, txn_type: str, description: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE id = ?",
                (amount, amount, user_id),
            )
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, amount, txn_type, description),
            )

    def spend_balance(self, user_id: int, amount: int, description: str) -> bool:
        """Atomically debit a stake only when the current balance covers it."""
        if amount <= 0:
            return False
        with closing(self._connect()) as conn, conn:
            updated = conn.execute(
                "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
                (amount, user_id, amount),
            )
            if updated.rowcount != 1:
                return False
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, -amount, "game_bet", description),
            )
            return True

    def start_mines_round(self, game) -> bool:
        """Store the board and debit its stake in the same transaction."""
        try:
            with closing(self._connect()) as conn, conn:
                updated = conn.execute(
                    "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
                    (game.bet, game.user_id, game.bet),
                )
                if updated.rowcount != 1:
                    return False
                inserted = conn.execute(
                    "INSERT OR IGNORE INTO active_mines "
                    "(user_id, round_id, bet, mine_count, seed, house_edge, revealed) "
                    "VALUES (?, ?, ?, ?, ?, ?, '[]')",
                    (game.user_id, game.public_id, game.bet, game.mines, game.seed, game.house_edge),
                )
                if inserted.rowcount != 1:
                    raise _MinesConflict()
                conn.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) "
                    "VALUES (?, ?, 'game_bet', ?)",
                    (game.user_id, -game.bet, "Ставка в игре Мины"),
                )
                return True
        except _MinesConflict:
            return False

    def get_active_mines(self, user_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM active_mines WHERE user_id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def save_mines_round(self, game) -> bool:
        with closing(self._connect()) as conn, conn:
            updated = conn.execute(
                "UPDATE active_mines SET revealed = ? WHERE user_id = ? AND round_id = ?",
                (json.dumps(sorted(game.revealed)), game.user_id, game.public_id),
            )
            return updated.rowcount == 1

    def settle_mines_round(self, game, result: str) -> bool:
        """Finish once; the payout, ledger and statistics commit together."""
        if result not in ("win", "lose", "cancel"):
            raise ValueError("invalid Mines result")
        payout = game.payout if result == "win" else game.bet if result == "cancel" else 0
        with closing(self._connect()) as conn, conn:
            deleted = conn.execute(
                "DELETE FROM active_mines WHERE user_id = ? AND round_id = ?",
                (game.user_id, game.public_id),
            )
            if deleted.rowcount != 1:
                return False
            if payout:
                rubies = round(payout / 50000 * 0.1, 2) if result == "win" and payout >= 50000 else 0
                conn.execute(
                    "UPDATE users SET balance = balance + ?, "
                    "max_balance = MAX(COALESCE(max_balance, 0), balance + ?), "
                    "rubies = rubies + ? WHERE id = ?",
                    (payout, payout, rubies, game.user_id),
                )
                conn.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                    (game.user_id, payout, "game_win" if result == "win" else "game_bet",
                     "Выигрыш в игре Мины" if result == "win" else "Возврат ставки"),
                )
            conn.execute(
                "INSERT INTO games (user_id, game_type, bet, win_amount, result) "
                "VALUES (?, 'mines', ?, ?, ?)",
                (game.user_id, game.bet, payout, result),
            )
            if result != "cancel":
                self._ensure_stats(conn, game.user_id)
                conn.execute(
                    "UPDATE stats SET total_games = total_games + 1, "
                    "wins = wins + ?, losses = losses + ?, "
                    "total_bet = total_bet + ?, total_won = total_won + ? "
                    "WHERE user_id = ?",
                    (int(result == "win"), int(result == "lose"), game.bet,
                     payout if result == "win" else 0, game.user_id),
                )
            return True

    def add_rubies(self, user_id: int, amount: float) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET rubies = rubies + ? WHERE id = ?",
                (amount, user_id),
            )

    # ---------- Транзакции ----------

    def get_transactions(self, user_id: int, limit: int = 10, *, offset: int = 0,
                         category: str = "all", before_id: int | None = None) -> list[dict]:
        if limit < 1 or offset < 0:
            raise ValueError("Invalid history page")
        where, params = _transaction_where(user_id, category, before_id, "?")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM transactions WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_transactions(self, user_id: int, *, category: str = "all",
                           before_id: int | None = None) -> int:
        where, params = _transaction_where(user_id, category, before_id, "?")
        with closing(self._connect()) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM transactions WHERE {where}", params).fetchone()[0]

    def set_bonus_reminder(self, user_id: int, kind: str, enabled: bool) -> None:
        if kind not in ("daily", "weekly"):
            raise ValueError("Unknown bonus reminder")
        with closing(self._connect()) as conn, conn:
            conn.execute(f"UPDATE users SET {kind}_reminder_enabled = ? WHERE id = ?",
                         (int(enabled), user_id))

    # ---------- Статистика ----------

    def _ensure_stats(self, conn: sqlite3.Connection, user_id: int) -> None:
        conn.execute("INSERT OR IGNORE INTO stats (user_id) VALUES (?)", (user_id,))

    def get_stats(self, user_id: int) -> dict:
        with closing(self._connect()) as conn, conn:
            self._ensure_stats(conn, user_id)
            row = conn.execute(
                "SELECT * FROM stats WHERE user_id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else {
                "user_id": user_id,
                "total_games": 0,
                "wins": 0,
                "losses": 0,
                "total_bet": 0,
                "total_won": 0,
            }

    def update_stats(self, user_id: int, result: str, bet: int, win_amount: int) -> None:
        with closing(self._connect()) as conn, conn:
            self._ensure_stats(conn, user_id)
            if result == "win":
                conn.execute(
                    """
                    UPDATE stats
                    SET total_games = total_games + 1,
                        wins = wins + 1,
                        total_bet = total_bet + ?,
                        total_won = total_won + ?
                    WHERE user_id = ?
                    """,
                    (bet, win_amount, user_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE stats
                    SET total_games = total_games + 1,
                        losses = losses + 1,
                        total_bet = total_bet + ?
                    WHERE user_id = ?
                    """,
                    (bet, user_id),
                )

    # ---------- Игры ----------

    def add_game(self, user_id: int, game_type: str, bet: int, win_amount: int, result: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO games (user_id, game_type, bet, win_amount, result) VALUES (?, ?, ?, ?, ?)",
                (user_id, game_type, bet, win_amount, result),
            )

    # ---------- Ежедневный бонус ----------

    def claim_daily(self, user_id: int, amount: int) -> bool:
        today = date.today().isoformat()
        with closing(self._connect()) as conn, conn:
            result = conn.execute(
                "UPDATE users SET balance = balance + ?, last_daily = ?, daily_notified = 0, "
                "max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE id = ? "
                "AND (last_daily IS NULL OR last_daily != ?)",
                (amount, today, amount, user_id, today),
            )
            if result.rowcount != 1:
                return False
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, amount, "daily", "Ежедневный бонус"),
            )
            return True

    def claim_weekly(self, user_id: int, amount: int) -> bool:
        week = current_week()
        with closing(self._connect()) as conn, conn:
            result = conn.execute(
                "UPDATE users SET balance = balance + ?, last_weekly = ?, weekly_notified = 0, "
                "max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE id = ? "
                "AND (last_weekly IS NULL OR last_weekly != ?)",
                (amount, week, amount, user_id, week),
            )
            if result.rowcount != 1:
                return False
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, amount, "weekly", "Еженедельный бонус"),
            )
            return True

    def get_daily_eligible(self) -> list[dict]:
        """Игроки, которым можно напомнить про ежедневный бонус (забрали раньше, сегодня ещё нет)."""
        today = date.today().isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id FROM users
                WHERE is_blocked = 0
                  AND last_daily IS NOT NULL
                  AND last_daily != ?
                  AND daily_notified = 0
                  AND daily_reminder_enabled = 1
                """,
                (today,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_weekly_eligible(self) -> list[dict]:
        """Игроки, которым можно напомнить про еженедельный бонус (забирали раньше, в эту неделю ещё нет)."""
        week = current_week()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT id FROM users
                WHERE is_blocked = 0
                  AND last_weekly IS NOT NULL
                  AND last_weekly != ?
                  AND weekly_notified = 0
                  AND weekly_reminder_enabled = 1
                """,
                (week,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_daily_notified(self, user_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET daily_notified = 1 WHERE id = ?", (user_id,)
            )

    def mark_weekly_notified(self, user_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET weekly_notified = 1 WHERE id = ?", (user_id,)
            )

    # ---------- Рейтинг ----------

    def top_balance(self, limit: int = 10) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, username, first_name, balance FROM users ORDER BY balance DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def top_max_balance(self, limit: int = 10) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, username, first_name, max_balance FROM users ORDER BY max_balance DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def top_wins(self, limit: int = 10) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.first_name, u.balance, s.wins
                FROM users u JOIN stats s ON s.user_id = u.id
                ORDER BY s.wins DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def top_xp(self, limit: int = 10) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, username, first_name, balance, xp FROM users ORDER BY xp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- Админ ----------

    def admin_overview(self) -> dict:
        with closing(self._connect()) as conn:
            users = conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(balance), 0) AS b FROM users"
            ).fetchone()
            games = conn.execute("SELECT COUNT(*) AS c FROM games").fetchone()
            wins = conn.execute(
                "SELECT COUNT(*) AS c FROM games WHERE result = 'win'"
            ).fetchone()
            tx = conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(amount), 0) AS s FROM transactions"
            ).fetchone()
            return {
                "users": users["c"],
                "balance": users["b"],
                "games": games["c"],
                "wins": wins["c"],
                "tx_count": tx["c"],
                "tx_volume": tx["s"],
            }

    # ---------- Настройки ----------

    def get_setting(self, key: str, default) -> str:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )

    # ---------- Промокоды ----------

    def create_promo(self, code: str, amount: int, max_uses: int) -> bool:
        code = (code or "").strip().upper()
        if not code or amount <= 0 or max_uses < 1:
            return False
        with closing(self._connect()) as conn, conn:
            try:
                conn.execute(
                    "INSERT INTO promos (code, amount, max_uses) VALUES (?, ?, ?)",
                    (code, amount, max_uses),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def get_promo(self, code: str) -> dict | None:
        code = (code or "").strip().upper()
        if not code:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM promos WHERE code = ?", (code,)
            ).fetchone()
            return dict(row) if row else None

    def get_promo_by_id(self, promo_id: int) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM promos WHERE id = ?", (promo_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_promos(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM promos ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_promo(self, promo_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM promo_claims WHERE promo_id = ?", (promo_id,))
            conn.execute("DELETE FROM promos WHERE id = ?", (promo_id,))

    def toggle_promo(self, promo_id: int, active: bool) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE promos SET is_active = ? WHERE id = ?",
                (1 if active else 0, promo_id),
            )

    def redeem_promo(self, user_id: int, code: str) -> tuple[str, int]:
        """Активирует промокод. Возвращает (статус, сумма).
        Статусы: ok, not_found, inactive, used_up, already."""
        promo = self.get_promo(code)
        if not promo:
            return ("not_found", 0)
        if not promo["is_active"]:
            return ("inactive", 0)
        if promo["used_count"] >= promo["max_uses"]:
            return ("used_up", 0)
        with closing(self._connect()) as conn, conn:
            claimed = conn.execute(
                "SELECT 1 FROM promo_claims WHERE promo_id = ? AND user_id = ?",
                (promo["id"], user_id),
            ).fetchone()
            if claimed:
                return ("already", 0)
            conn.execute(
                "INSERT INTO promo_claims (promo_id, user_id) VALUES (?, ?)",
                (promo["id"], user_id),
            )
            conn.execute(
                "UPDATE promos SET used_count = used_count + 1 WHERE id = ?",
                (promo["id"],),
            )
            conn.execute(
                "UPDATE users SET balance = balance + ?, max_balance = MAX(COALESCE(max_balance, 0), balance + ?) WHERE id = ?",
                (promo["amount"], promo["amount"], user_id),
            )
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, promo["amount"], "promo", f"Промокод {promo['code']}"),
            )
        return ("ok", promo["amount"])

    def reset_database(self) -> None:
        """Полный сброс: всем баланс на стартовый, обнуление статистики и истории."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET balance = ?, max_balance = ?, xp = 0, "
                "last_daily = NULL, last_weekly = NULL, "
                "daily_notified = 0, weekly_notified = 0",
                (STARTING_BALANCE, STARTING_BALANCE),
            )
            conn.execute(
                "UPDATE stats SET total_games = 0, wins = 0, losses = 0, "
                "total_bet = 0, total_won = 0"
            )
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM games")
            conn.execute("DELETE FROM promo_claims")
            conn.execute("DELETE FROM user_achievements")
            conn.execute("DELETE FROM user_showcase")
            conn.execute("UPDATE promos SET used_count = 0")

    # ---------- Магазин ----------

    def owns_item(self, user_id: int, item_id: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM user_purchases WHERE user_id = ? AND item_id = ?",
                (user_id, item_id),
            ).fetchone()
            return row is not None

    def buy_item(self, user_id: int, item_id: str, category: str, price: int) -> bool:
        with closing(self._connect()) as conn, conn:
            user = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user or user["balance"] < price:
                return False
            conn.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (price, user_id))
            conn.execute(
                "INSERT OR IGNORE INTO user_purchases (user_id, item_id, category) VALUES (?, ?, ?)",
                (user_id, item_id, category),
            )
            conn.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                (user_id, -price, "shop", f"Покупка: {item_id}"),
            )
            return True

    def set_active_frame(self, user_id: int, frame: str | None) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE users SET active_frame = ? WHERE id = ?", (frame, user_id))

    def set_active_title(self, user_id: int, title: str | None) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE users SET active_title = ? WHERE id = ?", (title, user_id))

    def get_purchases(self, user_id: int) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT item_id, category FROM user_purchases WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------- Достижения ----------

    def get_achievements(self, user_id: int) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT achievement_id FROM user_achievements WHERE user_id = ?",
                (user_id,),
            ).fetchall()
            return [r["achievement_id"] for r in rows]

    def grant_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Выдаёт ачивку. True если новая, False если уже была."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
                (user_id, achievement_id),
            )
            return cur.rowcount > 0

    def get_showcase(self, user_id: int) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT achievement_id FROM user_showcase WHERE user_id = ? ORDER BY position",
                (user_id,),
            ).fetchall()
            return [row["achievement_id"] for row in rows]

    def toggle_showcase(self, user_id: int, achievement_id: str) -> str:
        """Add or remove an earned award; return added, removed, full or not_earned."""
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT position FROM user_showcase WHERE user_id = ? AND achievement_id = ?",
                (user_id, achievement_id),
            ).fetchone()
            if current:
                conn.execute(
                    "DELETE FROM user_showcase WHERE user_id = ? AND achievement_id = ?",
                    (user_id, achievement_id),
                )
                return "removed"
            earned = conn.execute(
                "SELECT 1 FROM user_achievements WHERE user_id = ? AND achievement_id = ?",
                (user_id, achievement_id),
            ).fetchone()
            if not earned:
                return "not_earned"
            positions = {row["position"] for row in conn.execute(
                "SELECT position FROM user_showcase WHERE user_id = ?", (user_id,),
            )}
            if len(positions) >= 3:
                return "full"
            position = next(slot for slot in range(3) if slot not in positions)
            conn.execute(
                "INSERT INTO user_showcase (user_id, achievement_id, position) VALUES (?, ?, ?)",
                (user_id, achievement_id, position),
            )
            return "added"

    # ---------- XP / Уровни ----------

    def add_xp(self, user_id: int, amount: int) -> tuple[int, int]:
        """Добавляет XP одним запросом. Возвращает (new_xp, new_level)."""
        with closing(self._connect()) as conn, conn:
            try:
                row = conn.execute(
                    "UPDATE users SET xp = xp + ? WHERE id = ? RETURNING xp",
                    (amount, user_id),
                ).fetchone()
                new_xp = row["xp"] if row else 0
            except sqlite3.OperationalError:
                conn.execute(
                    "UPDATE users SET xp = xp + ? WHERE id = ?",
                    (amount, user_id),
                )
                row = conn.execute("SELECT xp FROM users WHERE id = ?", (user_id,)).fetchone()
                new_xp = row["xp"] if row else 0
            return new_xp, _calc_level(new_xp)

    def get_xp(self, user_id: int) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT xp FROM users WHERE id = ?", (user_id,)).fetchone()
            return row["xp"] if row else 0


class PostgresDatabase:
    """Слой работы с PostgreSQL (для облачного хостинга)."""

    def __init__(self, url: str = DATABASE_URL):
        self.url = url
        self._pool = None
        self.init_db()

    def _get_conn(self):
        if self._pool is None:
            self._pool = psycopg2.pool.SimpleConnectionPool(1, 10, self.url)
        return self._pool.getconn()

    def _put_conn(self, conn) -> None:
        self._pool.putconn(conn)

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        try:
            with conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                yield cur
        finally:
            self._put_conn(conn)

    def init_db(self) -> None:
        with self._cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    balance BIGINT NOT NULL DEFAULT 0,
                    rubies DOUBLE PRECISION NOT NULL DEFAULT 0,
                    is_blocked INTEGER NOT NULL DEFAULT 0,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    last_daily TEXT,
                    created_at TEXT NOT NULL DEFAULT (to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'))
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stats (
                    user_id BIGINT PRIMARY KEY,
                    total_games INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    total_bet BIGINT NOT NULL DEFAULT 0,
                    total_won BIGINT NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount BIGINT NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL DEFAULT (to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'))
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    game_type TEXT NOT NULL,
                    bet BIGINT NOT NULL,
                    win_amount BIGINT NOT NULL DEFAULT 0,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'))
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS active_mines (
                    user_id BIGINT PRIMARY KEY,
                    round_id TEXT NOT NULL UNIQUE,
                    bet BIGINT NOT NULL,
                    mine_count INTEGER NOT NULL,
                    seed TEXT NOT NULL,
                    house_edge DOUBLE PRECISION NOT NULL,
                    revealed TEXT NOT NULL DEFAULT '[]'
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_notified INTEGER NOT NULL DEFAULT 0"
            )
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_weekly TEXT")
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS weekly_notified INTEGER NOT NULL DEFAULT 0"
            )
            for kind in ("daily", "weekly"):
                cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {kind}_reminder_enabled INTEGER NOT NULL DEFAULT 1")
            cur.execute("CREATE INDEX IF NOT EXISTS transactions_user_id_idx ON transactions (user_id, id)")
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS max_balance BIGINT NOT NULL DEFAULT 0"
            )
            cur.execute(
                "UPDATE users SET max_balance = balance WHERE max_balance = 0"
            )
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT")
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER NOT NULL DEFAULT 0"
            )
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_earned BIGINT NOT NULL DEFAULT 0"
            )
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS rubies DOUBLE PRECISION NOT NULL DEFAULT 0"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS promos (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    amount BIGINT NOT NULL,
                    max_uses INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'))
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS promo_claims (
                    id BIGSERIAL PRIMARY KEY,
                    promo_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')),
                    UNIQUE(promo_id, user_id)
                )
            """)
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS active_frame TEXT"
            )
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS active_title TEXT"
            )
            cur.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS xp BIGINT NOT NULL DEFAULT 0"
            )
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_purchases (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    item_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')),
                    UNIQUE(user_id, item_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id BIGINT NOT NULL,
                    achievement_id TEXT NOT NULL,
                    earned_at TEXT NOT NULL DEFAULT (to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')),
                    PRIMARY KEY (user_id, achievement_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_showcase (
                    user_id BIGINT NOT NULL,
                    achievement_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (user_id, achievement_id),
                    UNIQUE (user_id, position)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mobile_sessions (
                    id TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    device_label TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    last_seen_at BIGINT NOT NULL,
                    expires_at BIGINT NOT NULL,
                    revoked_at BIGINT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS mobile_sessions_user_idx ON mobile_sessions(user_id)")

    def create_mobile_session(self, user_id: int, device_label: str, expires_at: int) -> str:
        session_id = secrets.token_urlsafe(24)
        now = int(time.time())
        with self._cursor() as cur:
            cur.execute("DELETE FROM mobile_sessions WHERE expires_at <= %s", (now,))
            cur.execute("""
                INSERT INTO mobile_sessions
                    (id, user_id, device_label, created_at, last_seen_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (session_id, user_id, device_label, now, now, expires_at))
        return session_id

    def get_mobile_session(self, session_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM mobile_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def touch_mobile_session(self, session_id: str, now: int) -> None:
        with self._cursor() as cur:
            cur.execute("""
                UPDATE mobile_sessions SET last_seen_at = %s
                WHERE id = %s AND last_seen_at <= %s AND revoked_at IS NULL
            """, (now, session_id, now - 300))

    def list_mobile_sessions(self, user_id: int) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("""
                SELECT id, device_label, created_at, last_seen_at, expires_at
                FROM mobile_sessions
                WHERE user_id = %s AND revoked_at IS NULL AND expires_at > %s
                ORDER BY last_seen_at DESC, created_at DESC
            """, (user_id, int(time.time())))
            return [dict(row) for row in cur.fetchall()]

    def revoke_mobile_session(self, user_id: int, session_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("""
                UPDATE mobile_sessions SET revoked_at = %s
                WHERE user_id = %s AND id = %s AND revoked_at IS NULL
            """, (int(time.time()), user_id, session_id))
            return cur.rowcount > 0

    def revoke_other_mobile_sessions(self, user_id: int, current_id: str | None) -> int:
        with self._cursor() as cur:
            cur.execute("""
                UPDATE mobile_sessions SET revoked_at = %s
                WHERE user_id = %s AND id <> %s AND revoked_at IS NULL
                  AND expires_at > %s
            """, (int(time.time()), user_id, current_id or "", int(time.time())))
            return cur.rowcount

    # ---------- Пользователи ----------

    def register_user(self, user_id: int, username, first_name, referrer_id: int | None = None) -> None:
        is_admin = 1 if user_id in ADMIN_IDS else 0
        with self._cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
            new = cur.fetchone() is None
            cur.execute(
                """
                INSERT INTO users (id, username, first_name, balance, is_admin, last_daily, referrer_id)
                VALUES (%s, %s, %s, %s, %s, NULL, %s)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name
                """,
                (user_id, username, first_name, STARTING_BALANCE, is_admin, referrer_id),
            )
            cur.execute(
                "INSERT INTO stats (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            if new:
                cur.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) VALUES (%s, %s, %s, %s)",
                    (user_id, STARTING_BALANCE, "bonus", "Приветственный бонус"),
                )
                if referrer_id and referrer_id != user_id:
                    cur.execute("SELECT 1 FROM users WHERE id = %s", (referrer_id,))
                    if cur.fetchone():
                        cur.execute(
                            "UPDATE users SET referral_count = referral_count + 1 WHERE id = %s",
                            (referrer_id,),
                        )

    def add_referral_earning(self, user_id: int, amount: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET referral_earned = referral_earned + %s WHERE id = %s",
                (amount, user_id),
            )

    def get_user(self, user_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        username = (username or "").lstrip("@").lower()
        if not username:
            return None
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE lower(username) = %s LIMIT 1", (username,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def search_users(self, query: str, limit: int = 50) -> list[dict]:
        """Поиск игроков по ID, имени или username (для веб-админки)."""
        query = (query or "").strip().lstrip("@")
        with self._cursor() as cur:
            if not query:
                cur.execute(
                    "SELECT * FROM users ORDER BY balance DESC LIMIT %s", (limit,)
                )
                return [dict(r) for r in cur.fetchall()]
            if query.isdigit():
                cur.execute("SELECT * FROM users WHERE id = %s LIMIT 1", (int(query),))
                row = cur.fetchone()
                return [dict(row)] if row else []
            cur.execute(
                """
                SELECT * FROM users
                WHERE lower(username) LIKE %s OR lower(first_name) LIKE %s
                ORDER BY balance DESC LIMIT %s
                """,
                (f"%{query.lower()}%", f"%{query.lower()}%", limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def is_user_blocked(self, user_id: int) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT is_blocked FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return bool(row and row["is_blocked"])

    def set_blocked(self, user_id: int, blocked: bool) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET is_blocked = %s WHERE id = %s",
                (1 if blocked else 0, user_id),
            )

    def add_balance(self, user_id: int, amount: int, txn_type: str, description: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET balance = balance + %s, max_balance = GREATEST(COALESCE(max_balance, 0), balance + %s) WHERE id = %s",
                (amount, amount, user_id),
            )
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (%s, %s, %s, %s)",
                (user_id, amount, txn_type, description),
            )

    def spend_balance(self, user_id: int, amount: int, description: str) -> bool:
        """Atomically debit a stake only when the current balance covers it."""
        if amount <= 0:
            return False
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET balance = balance - %s WHERE id = %s AND balance >= %s",
                (amount, user_id, amount),
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (%s, %s, %s, %s)",
                (user_id, -amount, "game_bet", description),
            )
            return True

    def start_mines_round(self, game) -> bool:
        """Store the board and debit its stake in the same transaction."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE users SET balance = balance - %s WHERE id = %s AND balance >= %s",
                    (game.bet, game.user_id, game.bet),
                )
                if cur.rowcount != 1:
                    return False
                cur.execute(
                    "INSERT INTO active_mines "
                    "(user_id, round_id, bet, mine_count, seed, house_edge, revealed) "
                    "VALUES (%s, %s, %s, %s, %s, %s, '[]') ON CONFLICT (user_id) DO NOTHING",
                    (game.user_id, game.public_id, game.bet, game.mines, game.seed, game.house_edge),
                )
                if cur.rowcount != 1:
                    raise _MinesConflict()
                cur.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) "
                    "VALUES (%s, %s, 'game_bet', %s)",
                    (game.user_id, -game.bet, "Ставка в игре Мины"),
                )
                return True
        except _MinesConflict:
            return False

    def get_active_mines(self, user_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM active_mines WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def save_mines_round(self, game) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE active_mines SET revealed = %s WHERE user_id = %s AND round_id = %s",
                (json.dumps(sorted(game.revealed)), game.user_id, game.public_id),
            )
            return cur.rowcount == 1

    def settle_mines_round(self, game, result: str) -> bool:
        """Finish once; the payout, ledger and statistics commit together."""
        if result not in ("win", "lose", "cancel"):
            raise ValueError("invalid Mines result")
        payout = game.payout if result == "win" else game.bet if result == "cancel" else 0
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM active_mines WHERE user_id = %s AND round_id = %s",
                (game.user_id, game.public_id),
            )
            if cur.rowcount != 1:
                return False
            if payout:
                rubies = round(payout / 50000 * 0.1, 2) if result == "win" and payout >= 50000 else 0
                cur.execute(
                    "UPDATE users SET balance = balance + %s, "
                    "max_balance = GREATEST(COALESCE(max_balance, 0), balance + %s), "
                    "rubies = rubies + %s WHERE id = %s",
                    (payout, payout, rubies, game.user_id),
                )
                cur.execute(
                    "INSERT INTO transactions (user_id, amount, type, description) "
                    "VALUES (%s, %s, %s, %s)",
                    (game.user_id, payout, "game_win" if result == "win" else "game_bet",
                     "Выигрыш в игре Мины" if result == "win" else "Возврат ставки"),
                )
            cur.execute(
                "INSERT INTO games (user_id, game_type, bet, win_amount, result) "
                "VALUES (%s, 'mines', %s, %s, %s)",
                (game.user_id, game.bet, payout, result),
            )
            if result != "cancel":
                self._ensure_stats(cur, game.user_id)
                cur.execute(
                    "UPDATE stats SET total_games = total_games + 1, "
                    "wins = wins + %s, losses = losses + %s, "
                    "total_bet = total_bet + %s, total_won = total_won + %s "
                    "WHERE user_id = %s",
                    (int(result == "win"), int(result == "lose"), game.bet,
                     payout if result == "win" else 0, game.user_id),
                )
            return True

    def add_rubies(self, user_id: int, amount: float) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET rubies = rubies + %s WHERE id = %s",
                (amount, user_id),
            )

    # ---------- Транзакции ----------

    def get_transactions(self, user_id: int, limit: int = 10, *, offset: int = 0,
                         category: str = "all", before_id: int | None = None) -> list[dict]:
        if limit < 1 or offset < 0:
            raise ValueError("Invalid history page")
        where, params = _transaction_where(user_id, category, before_id, "%s")
        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM transactions WHERE {where} ORDER BY id DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            )
            return [dict(r) for r in cur.fetchall()]

    def count_transactions(self, user_id: int, *, category: str = "all",
                           before_id: int | None = None) -> int:
        where, params = _transaction_where(user_id, category, before_id, "%s")
        with self._cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM transactions WHERE {where}", params)
            return cur.fetchone()["total"]

    def set_bonus_reminder(self, user_id: int, kind: str, enabled: bool) -> None:
        if kind not in ("daily", "weekly"):
            raise ValueError("Unknown bonus reminder")
        with self._cursor() as cur:
            cur.execute(f"UPDATE users SET {kind}_reminder_enabled = %s WHERE id = %s",
                        (int(enabled), user_id))

    # ---------- Статистика ----------

    def _ensure_stats(self, cur, user_id: int) -> None:
        cur.execute(
            "INSERT INTO stats (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
            (user_id,),
        )

    def get_stats(self, user_id: int) -> dict:
        with self._cursor() as cur:
            self._ensure_stats(cur, user_id)
            cur.execute("SELECT * FROM stats WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else {
                "user_id": user_id,
                "total_games": 0,
                "wins": 0,
                "losses": 0,
                "total_bet": 0,
                "total_won": 0,
            }

    def update_stats(self, user_id: int, result: str, bet: int, win_amount: int) -> None:
        with self._cursor() as cur:
            self._ensure_stats(cur, user_id)
            if result == "win":
                cur.execute(
                    """
                    UPDATE stats
                    SET total_games = total_games + 1,
                        wins = wins + 1,
                        total_bet = total_bet + %s,
                        total_won = total_won + %s
                    WHERE user_id = %s
                    """,
                    (bet, win_amount, user_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE stats
                    SET total_games = total_games + 1,
                        losses = losses + 1,
                        total_bet = total_bet + %s
                    WHERE user_id = %s
                    """,
                    (bet, user_id),
                )

    # ---------- Игры ----------

    def add_game(self, user_id: int, game_type: str, bet: int, win_amount: int, result: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO games (user_id, game_type, bet, win_amount, result) VALUES (%s, %s, %s, %s, %s)",
                (user_id, game_type, bet, win_amount, result),
            )

    # ---------- Ежедневный бонус ----------

    def claim_daily(self, user_id: int, amount: int) -> bool:
        today = date.today().isoformat()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET balance = balance + %s, last_daily = %s, daily_notified = 0, "
                "max_balance = GREATEST(COALESCE(max_balance, 0), balance + %s) WHERE id = %s "
                "AND (last_daily IS NULL OR last_daily != %s)",
                (amount, today, amount, user_id, today),
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (%s, %s, %s, %s)",
                (user_id, amount, "daily", "Ежедневный бонус"),
            )
            return True

    def claim_weekly(self, user_id: int, amount: int) -> bool:
        week = current_week()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET balance = balance + %s, last_weekly = %s, weekly_notified = 0, "
                "max_balance = GREATEST(COALESCE(max_balance, 0), balance + %s) WHERE id = %s "
                "AND (last_weekly IS NULL OR last_weekly != %s)",
                (amount, week, amount, user_id, week),
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (%s, %s, %s, %s)",
                (user_id, amount, "weekly", "Еженедельный бонус"),
            )
            return True

    def get_daily_eligible(self) -> list[dict]:
        today = date.today().isoformat()
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT id FROM users
                WHERE is_blocked = 0
                  AND last_daily IS NOT NULL
                  AND last_daily != %s
                  AND daily_notified = 0
                  AND daily_reminder_enabled = 1
                """,
                (today,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_weekly_eligible(self) -> list[dict]:
        week = current_week()
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT id FROM users
                WHERE is_blocked = 0
                  AND last_weekly IS NOT NULL
                  AND last_weekly != %s
                  AND weekly_notified = 0
                  AND weekly_reminder_enabled = 1
                """,
                (week,),
            )
            return [dict(r) for r in cur.fetchall()]

    def mark_daily_notified(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE users SET daily_notified = 1 WHERE id = %s", (user_id,))

    def mark_weekly_notified(self, user_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE users SET weekly_notified = 1 WHERE id = %s", (user_id,))

    # ---------- Рейтинг ----------

    def top_balance(self, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, username, first_name, balance FROM users ORDER BY balance DESC LIMIT %s",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def top_max_balance(self, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, username, first_name, max_balance FROM users ORDER BY max_balance DESC LIMIT %s",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def top_wins(self, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.username, u.first_name, u.balance, s.wins
                FROM users u JOIN stats s ON s.user_id = u.id
                ORDER BY s.wins DESC LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    def top_xp(self, limit: int = 10) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, username, first_name, balance, xp FROM users ORDER BY xp DESC LIMIT %s",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]

    # ---------- Админ ----------

    def admin_overview(self) -> dict:
        with self._cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(balance), 0) AS b FROM users"
            )
            users = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS c FROM games")
            games = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS c FROM games WHERE result = 'win'")
            wins = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(amount), 0) AS s FROM transactions"
            )
            tx = cur.fetchone()
            return {
                "users": users["c"],
                "balance": users["b"],
                "games": games["c"],
                "wins": wins["c"],
                "tx_count": tx["c"],
                "tx_volume": tx["s"],
            }

    # ---------- Настройки ----------

    def get_setting(self, key: str, default) -> str:
        with self._cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, str(value)),
            )

    # ---------- Промокоды ----------

    def create_promo(self, code: str, amount: int, max_uses: int) -> bool:
        code = (code or "").strip().upper()
        if not code or amount <= 0 or max_uses < 1:
            return False
        with self._cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO promos (code, amount, max_uses) VALUES (%s, %s, %s)",
                    (code, amount, max_uses),
                )
            except psycopg2.errors.UniqueViolation:
                return False
        return True

    def get_promo(self, code: str) -> dict | None:
        code = (code or "").strip().upper()
        if not code:
            return None
        with self._cursor() as cur:
            cur.execute("SELECT * FROM promos WHERE code = %s", (code,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_promo_by_id(self, promo_id: int) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM promos WHERE id = %s", (promo_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_promos(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM promos ORDER BY id DESC")
            return [dict(r) for r in cur.fetchall()]

    def delete_promo(self, promo_id: int) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM promo_claims WHERE promo_id = %s", (promo_id,))
            cur.execute("DELETE FROM promos WHERE id = %s", (promo_id,))

    def toggle_promo(self, promo_id: int, active: bool) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE promos SET is_active = %s WHERE id = %s",
                (1 if active else 0, promo_id),
            )

    def redeem_promo(self, user_id: int, code: str) -> tuple[str, int]:
        """Активирует промокод. Возвращает (статус, сумма).
        Статусы: ok, not_found, inactive, used_up, already."""
        promo = self.get_promo(code)
        if not promo:
            return ("not_found", 0)
        if not promo["is_active"]:
            return ("inactive", 0)
        if promo["used_count"] >= promo["max_uses"]:
            return ("used_up", 0)
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM promo_claims WHERE promo_id = %s AND user_id = %s",
                (promo["id"], user_id),
            )
            if cur.fetchone():
                return ("already", 0)
            cur.execute(
                "INSERT INTO promo_claims (promo_id, user_id) VALUES (%s, %s)",
                (promo["id"], user_id),
            )
            cur.execute(
                "UPDATE promos SET used_count = used_count + 1 WHERE id = %s",
                (promo["id"],),
            )
            cur.execute(
                "UPDATE users SET balance = balance + %s, max_balance = GREATEST(COALESCE(max_balance, 0), balance + %s) WHERE id = %s",
                (promo["amount"], promo["amount"], user_id),
            )
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (%s, %s, %s, %s)",
                (user_id, promo["amount"], "promo", f"Промокод {promo['code']}"),
            )
        return ("ok", promo["amount"])

    def reset_database(self) -> None:
        """Полный сброс: всем баланс на стартовый, обнуление статистики и истории."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET balance = %s, max_balance = %s, xp = 0, "
                "last_daily = NULL, last_weekly = NULL, "
                "daily_notified = 0, weekly_notified = 0",
                (STARTING_BALANCE, STARTING_BALANCE),
            )
            cur.execute(
                "UPDATE stats SET total_games = 0, wins = 0, losses = 0, "
                "total_bet = 0, total_won = 0"
            )
            cur.execute("DELETE FROM transactions")
            cur.execute("DELETE FROM games")
            cur.execute("DELETE FROM promo_claims")
            cur.execute("DELETE FROM user_achievements")
            cur.execute("DELETE FROM user_showcase")
            cur.execute("UPDATE promos SET used_count = 0")

    # ---------- Магазин ----------

    def owns_item(self, user_id: int, item_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM user_purchases WHERE user_id = %s AND item_id = %s",
                (user_id, item_id),
            )
            return cur.fetchone() is not None

    def buy_item(self, user_id: int, item_id: str, category: str, price: int) -> bool:
        with self._cursor() as cur:
            cur.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            if not row or row["balance"] < price:
                return False
            cur.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (price, user_id))
            cur.execute(
                "INSERT INTO user_purchases (user_id, item_id, category) VALUES (%s, %s, %s) "
                "ON CONFLICT (user_id, item_id) DO NOTHING",
                (user_id, item_id, category),
            )
            cur.execute(
                "INSERT INTO transactions (user_id, amount, type, description) VALUES (%s, %s, %s, %s)",
                (user_id, -price, "shop", f"Покупка: {item_id}"),
            )
            return True

    def set_active_frame(self, user_id: int, frame: str | None) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE users SET active_frame = %s WHERE id = %s", (frame, user_id))

    def set_active_title(self, user_id: int, title: str | None) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE users SET active_title = %s WHERE id = %s", (title, user_id))

    def get_purchases(self, user_id: int) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT item_id, category FROM user_purchases WHERE user_id = %s",
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    # ---------- Достижения ----------

    def get_achievements(self, user_id: int) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT achievement_id FROM user_achievements WHERE user_id = %s",
                (user_id,),
            )
            return [r["achievement_id"] for r in cur.fetchall()]

    def grant_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Выдаёт ачивку. True если новая, False если уже была."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO user_achievements (user_id, achievement_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id, achievement_id) DO NOTHING",
                (user_id, achievement_id),
            )
            return cur.rowcount > 0

    def get_showcase(self, user_id: int) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT achievement_id FROM user_showcase WHERE user_id = %s ORDER BY position",
                (user_id,),
            )
            return [row["achievement_id"] for row in cur.fetchall()]

    def toggle_showcase(self, user_id: int, achievement_id: str) -> str:
        """Serialize edits per player so no more than three awards can be shown."""
        with self._cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
            if not cur.fetchone():
                return "not_earned"
            cur.execute(
                "SELECT position FROM user_showcase WHERE user_id = %s AND achievement_id = %s",
                (user_id, achievement_id),
            )
            if cur.fetchone():
                cur.execute(
                    "DELETE FROM user_showcase WHERE user_id = %s AND achievement_id = %s",
                    (user_id, achievement_id),
                )
                return "removed"
            cur.execute(
                "SELECT 1 FROM user_achievements WHERE user_id = %s AND achievement_id = %s",
                (user_id, achievement_id),
            )
            if not cur.fetchone():
                return "not_earned"
            cur.execute("SELECT position FROM user_showcase WHERE user_id = %s", (user_id,))
            positions = {row["position"] for row in cur.fetchall()}
            if len(positions) >= 3:
                return "full"
            position = next(slot for slot in range(3) if slot not in positions)
            cur.execute(
                "INSERT INTO user_showcase (user_id, achievement_id, position) VALUES (%s, %s, %s)",
                (user_id, achievement_id, position),
            )
            return "added"

    # ---------- XP / Уровни ----------

    def add_xp(self, user_id: int, amount: int) -> tuple[int, int]:
        """Добавляет XP одним запросом. Возвращает (new_xp, new_level)."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE users SET xp = xp + %s WHERE id = %s RETURNING xp",
                (amount, user_id),
            )
            row = cur.fetchone()
            new_xp = row["xp"] if row else 0
            return new_xp, _calc_level(new_xp)

    def get_xp(self, user_id: int) -> int:
        with self._cursor() as cur:
            cur.execute("SELECT xp FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return row["xp"] if row else 0


db = PostgresDatabase() if DATABASE_URL else Database()
