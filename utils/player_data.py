"""Shared player features for SQLite and PostgreSQL."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta

GAMES = {
    "mines": {"name": "Мины", "icon": "💣", "command": "м"},
    "coinflip": {"name": "Монетка", "icon": "🪙", "command": "мон"},
    "joker": {"name": "Джокер", "icon": "🃏", "command": "дж"},
    "alchemist": {"name": "Алхимик", "icon": "⚗️", "command": "алх"},
    "blackjack": {"name": "21", "icon": "🂡", "command": "21"},
    "ruby_roulette": {"name": "Рулетка", "icon": "🎰", "command": None},
}


class PlayerFeaturesMixin:
    @property
    def _player_pg(self):
        return hasattr(self, "_cursor")

    @contextmanager
    def _player_cursor(self):
        if self._player_pg:
            with self._cursor() as cursor:
                yield cursor
        else:
            with closing(self._connect()) as conn, conn:
                yield conn.cursor()

    def _player_sql(self, sql):
        return sql.replace("?", "%s") if self._player_pg else sql

    def init_player_tables(self):
        binary = "BYTEA" if self._player_pg else "BLOB"
        with self._player_cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS user_preferences (
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                bio TEXT NOT NULL DEFAULT '', theme TEXT NOT NULL DEFAULT 'dark',
                hide_stats INTEGER NOT NULL DEFAULT 0, saved_bet BIGINT NOT NULL DEFAULT 100)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS user_favorites (
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                game_id TEXT NOT NULL, PRIMARY KEY(user_id, game_id))""")
            cur.execute(f"""CREATE TABLE IF NOT EXISTS user_avatars (
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                data {binary} NOT NULL, content_type TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS instant_rounds (
                user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                request_id TEXT NOT NULL, bet BIGINT NOT NULL, choice TEXT NOT NULL,
                result TEXT NOT NULL, payout BIGINT NOT NULL, won INTEGER NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(user_id, request_id))""")

    def get_player_preferences(self, user_id):
        with self._player_cursor() as cur:
            cur.execute(self._player_sql("SELECT bio, theme, hide_stats, saved_bet FROM user_preferences WHERE user_id = ?"), (user_id,))
            row = cur.fetchone()
            prefs = dict(row) if row else {"bio": "", "theme": "dark", "hide_stats": 0, "saved_bet": 100}
            cur.execute(self._player_sql("SELECT game_id FROM user_favorites WHERE user_id = ? ORDER BY game_id"), (user_id,))
            prefs["favorites"] = [row["game_id"] for row in cur.fetchall()]
            cur.execute(self._player_sql("SELECT content_type FROM user_avatars WHERE user_id = ?"), (user_id,))
            avatar = cur.fetchone()
            prefs["custom_avatar"] = avatar is not None
            prefs["hide_stats"] = bool(prefs["hide_stats"])
            return prefs

    def set_player_preferences(self, user_id, values):
        allowed = {"bio", "theme", "hide_stats", "saved_bet"}
        if not isinstance(values, dict) or not values or not set(values) <= allowed:
            raise ValueError("invalid preferences")
        if "bio" in values and (not isinstance(values["bio"], str) or len(values["bio"]) > 200):
            raise ValueError("invalid bio")
        if "theme" in values and values["theme"] not in ("dark", "light"):
            raise ValueError("invalid theme")
        if "hide_stats" in values and type(values["hide_stats"]) is not bool:
            raise ValueError("invalid privacy")
        if "saved_bet" in values:
            from config import MAX_BET, MIN_BET
            if type(values["saved_bet"]) is not int or not MIN_BET <= values["saved_bet"] <= MAX_BET:
                raise ValueError("invalid saved bet")
        fields = sorted(values)
        params = [int(values[field]) if field == "hide_stats" else values[field] for field in fields]
        with self._player_cursor() as cur:
            cur.execute(self._player_sql("INSERT INTO user_preferences(user_id) VALUES(?) ON CONFLICT(user_id) DO NOTHING"), (user_id,))
            cur.execute(self._player_sql("UPDATE user_preferences SET " + ", ".join(field + " = ?" for field in fields) + " WHERE user_id = ?"), (*params, user_id))

    def set_favorite(self, user_id, game_id, enabled):
        if game_id not in GAMES or type(enabled) is not bool:
            raise ValueError("invalid favorite")
        with self._player_cursor() as cur:
            if enabled:
                cur.execute(self._player_sql("INSERT INTO user_favorites(user_id, game_id) VALUES(?, ?) ON CONFLICT(user_id, game_id) DO NOTHING"), (user_id, game_id))
            else:
                cur.execute(self._player_sql("DELETE FROM user_favorites WHERE user_id = ? AND game_id = ?"), (user_id, game_id))

    def set_custom_avatar(self, user_id, data, content_type):
        from utils.avatars import MAX_IMAGE_BYTES
        if not data or len(data) > MAX_IMAGE_BYTES or content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            raise ValueError("invalid avatar")
        with self._player_cursor() as cur:
            cur.execute(self._player_sql("""INSERT INTO user_avatars(user_id, data, content_type, updated_at)
                VALUES(?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET
                data = excluded.data, content_type = excluded.content_type, updated_at = excluded.updated_at"""),
                (user_id, data, content_type, datetime.now().isoformat(timespec="seconds")))

    def get_custom_avatar(self, user_id):
        with self._player_cursor() as cur:
            cur.execute(self._player_sql("SELECT data, content_type FROM user_avatars WHERE user_id = ?"), (user_id,))
            row = cur.fetchone()
            return {"data": bytes(row["data"]), "content_type": row["content_type"]} if row else None

    def delete_custom_avatar(self, user_id):
        with self._player_cursor() as cur:
            cur.execute(self._player_sql("DELETE FROM user_avatars WHERE user_id = ?"), (user_id,))

    def player_statistics(self, user_id, days=30):
        if days not in (7, 30, 90):
            raise ValueError("invalid statistics period")
        today = datetime.now().date()
        start = today - timedelta(days=days - 1)
        with self._player_cursor() as cur:
            cur.execute(self._player_sql("""SELECT game_type, COUNT(*) AS games,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(bet) AS bets, SUM(win_amount) AS payouts FROM games
                WHERE user_id = ? AND created_at >= ? AND result IN ('win', 'lose') GROUP BY game_type"""), (user_id, start.isoformat()))
            games = [dict(row) for row in cur.fetchall()]
            cur.execute(self._player_sql("""SELECT SUBSTR(created_at, 1, 10) AS day, SUM(amount) AS change
                FROM transactions WHERE user_id = ? AND created_at >= ?
                GROUP BY SUBSTR(created_at, 1, 10) ORDER BY day"""), (user_id, start.isoformat()))
            changes = {row["day"]: int(row["change"]) for row in cur.fetchall()}
            cur.execute(self._player_sql("SELECT balance FROM users WHERE id = ?"), (user_id,))
            balance = cur.fetchone()["balance"]
        running = balance - sum(changes.values())
        points = [{"day": (start - timedelta(days=1)).isoformat(), "balance": running}]
        for offset in range(days):
            day = (start + timedelta(days=offset)).isoformat()
            running += changes.get(day, 0)
            points.append({"day": day, "balance": running})
        summary = {key: sum(int(game[key] or 0) for game in games) for key in ("games", "wins", "bets", "payouts")}
        summary["net"] = summary["payouts"] - summary["bets"]
        summary["winrate"] = round(summary["wins"] / summary["games"] * 100, 1) if summary["games"] else 0
        return {"days": days, "summary": summary, "games": games, "points": points}

    def player_leaderboard(self, user_id, mode="balance", period="all", limit=20):
        if mode not in ("balance", "xp", "wins", "games") or period not in ("all", "week", "month") or not 1 <= limit <= 50:
            raise ValueError("invalid leaderboard")
        if period != "all" and mode not in ("wins", "games"):
            raise ValueError("period rankings require games or wins")
        today = datetime.now().date()
        start = today - timedelta(days=today.weekday()) if period == "week" else today.replace(day=1)
        where, params = ("WHERE result IN ('win', 'lose')", []) if period == "all" else ("WHERE result IN ('win', 'lose') AND created_at >= ?", [start.isoformat()])
        metric = {"balance": "u.max_balance", "xp": "u.xp", "wins": "COALESCE(g.wins, 0)", "games": "COALESCE(g.total_games, 0)"}[mode]
        sql = f"""WITH scores AS (
            SELECT u.id, u.username, u.first_name, u.balance, u.max_balance, u.xp,
                COALESCE(g.wins, 0) AS wins, COALESCE(g.total_games, 0) AS total_games,
                {metric} AS score FROM users u LEFT JOIN (
                    SELECT user_id, COUNT(*) AS total_games,
                        SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) AS wins
                    FROM games {where} GROUP BY user_id
                ) g ON g.user_id = u.id
            LEFT JOIN user_preferences p ON p.user_id = u.id
            WHERE u.is_blocked = 0 AND COALESCE(p.hide_stats, 0) = 0
            {'AND COALESCE(g.total_games, 0) > 0' if mode in ('wins', 'games') else ''}
        ), ranked AS (SELECT *, ROW_NUMBER() OVER(ORDER BY score DESC, id ASC) AS rank FROM scores)
        SELECT * FROM ranked WHERE rank <= ? OR id = ? ORDER BY rank"""
        with self._player_cursor() as cur:
            cur.execute(self._player_sql(sql), (*params, limit, user_id))
            rows = [dict(row) for row in cur.fetchall()]
        me = next((row for row in rows if row["id"] == user_id), None)
        return {"mode": mode, "period": period, "players": [
            {**row, "user_id": row["id"], "is_me": row["id"] == user_id}
            for row in rows if row["rank"] <= limit], "my_rank": me["rank"] if me else None}

    def play_coinflip(self, user_id, request_id, bet, choice, result):
        from config import MAX_BET, MIN_BET
        from games.coinflip import PAYOUT_MULTIPLIER
        if not isinstance(request_id, str) or len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
            raise ValueError("invalid round id")
        if type(bet) is not int or not MIN_BET <= bet <= MAX_BET or choice not in ("орёл", "решка") or result not in ("орёл", "решка"):
            raise ValueError("invalid coinflip")
        with self._player_cursor() as cur:
            if not self._player_pg:
                cur.execute("BEGIN IMMEDIATE")
            cur.execute(self._player_sql("SELECT * FROM users WHERE id = ?" + (" FOR UPDATE" if self._player_pg else "")), (user_id,))
            user = cur.fetchone()
            if not user or user["is_blocked"]:
                return {"error": "account unavailable"}
            cur.execute(self._player_sql("SELECT * FROM instant_rounds WHERE user_id = ? AND request_id = ?"), (user_id, request_id))
            receipt = cur.fetchone()
            if receipt:
                if receipt["bet"] != bet or receipt["choice"] != choice:
                    return {"error": "round conflict"}
                return {**dict(receipt), "fresh": False}
            cur.execute(self._player_sql("SELECT user_id FROM active_mines WHERE user_id = ?"), (user_id,))
            if cur.fetchone():
                return {"error": "active game"}
            if user["balance"] < bet:
                return {"error": "insufficient balance"}
            won = choice == result
            payout = int(bet * PAYOUT_MULTIPLIER) if won else 0
            final = user["balance"] - bet + payout
            rubies = round(payout / 50000 * .1, 2) if payout >= 50000 else 0
            cur.execute(self._player_sql("""UPDATE users SET balance = ?,
                max_balance = CASE WHEN max_balance < ? THEN ? ELSE max_balance END,
                rubies = rubies + ?, xp = xp + ? WHERE id = ?"""), (final, final, final, rubies, 15 if won else 5, user_id))
            cur.execute(self._player_sql("INSERT INTO transactions(user_id, amount, type, description) VALUES(?, ?, 'game_bet', 'Ставка в Монетке')"), (user_id, -bet))
            if payout:
                cur.execute(self._player_sql("INSERT INTO transactions(user_id, amount, type, description) VALUES(?, ?, 'game_win', 'Выигрыш в Монетке')"), (user_id, payout))
            cur.execute(self._player_sql("INSERT INTO games(user_id, game_type, bet, win_amount, result) VALUES(?, 'coinflip', ?, ?, ?)"), (user_id, bet, payout, "win" if won else "lose"))
            cur.execute(self._player_sql("INSERT INTO stats(user_id) VALUES(?) ON CONFLICT(user_id) DO NOTHING"), (user_id,))
            cur.execute(self._player_sql("UPDATE stats SET total_games = total_games + 1, wins = wins + ?, losses = losses + ?, total_bet = total_bet + ?, total_won = total_won + ? WHERE user_id = ?"), (int(won), int(not won), bet, payout, user_id))
            referral = int(bet * .05)
            if user["referrer_id"] and referral:
                cur.execute(self._player_sql("""UPDATE users SET balance = balance + ?, referral_earned = referral_earned + ?,
                    max_balance = CASE WHEN max_balance < balance + ? THEN balance + ? ELSE max_balance END
                    WHERE id = ?"""), (referral, referral, referral, referral, user["referrer_id"]))
                if cur.rowcount:
                    cur.execute(self._player_sql("INSERT INTO transactions(user_id, amount, type, description) VALUES(?, ?, 'referral', 'Реферальный бонус: Монетка')"), (user["referrer_id"], referral))
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(self._player_sql("INSERT INTO instant_rounds(user_id, request_id, bet, choice, result, payout, won, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)"), (user_id, request_id, bet, choice, result, payout, int(won), now))
            return {"request_id": request_id, "bet": bet, "choice": choice, "result": result, "payout": payout, "won": won, "fresh": True}
