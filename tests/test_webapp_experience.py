"""Player HTTP contracts, run with both SQLite and real PostgreSQL in CI."""
import unittest
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from tests.test_webapp_mines import db, issue_session_token, register_webapp_routes
from tests.test_avatars import GIF
from utils.game_registry import registry


class PlayerApiTests(unittest.IsolatedAsyncioTestCase):
    next_user_id = 9930000

    async def asyncSetUp(self):
        type(self).next_user_id += 2
        self.uid = type(self).next_user_id
        self.other = self.uid + 1
        for uid in (self.uid, self.other):
            db.register_user(uid, None, "API player")
        app = web.Application()
        register_webapp_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer " + issue_session_token(self.uid)}
        self.other_headers = {"Authorization": "Bearer " + issue_session_token(self.other)}

    async def asyncTearDown(self):
        registry.release(self.uid)
        await self.client.close()

    async def request(self, method, path, **kwargs):
        return await self.client.request(method, "/app/api/" + path, headers=self.headers, **kwargs)

    async def test_all_new_routes_require_authentication(self):
        for method, path in (("GET", "hub"), ("GET", "bonuses"), ("POST", "bonuses/claim"),
                             ("PATCH", "bonuses/reminders"), ("GET", "history"),
                             ("GET", "history/export"), ("PATCH", "preferences"),
                             ("PUT", "favorites"), ("PUT", "profile/avatar"),
                             ("DELETE", "profile/avatar"), ("GET", "statistics"),
                             ("POST", "coinflip"), ("GET", "leaderboard")):
            response = await self.client.request(method, "/app/api/" + path)
            self.assertEqual(response.status, 401, path)
        with db._player_cursor() as cur:
            cur.execute(db._player_sql("UPDATE users SET is_blocked = 1 WHERE id = ?"), (self.uid,))
        self.assertEqual((await self.request("GET", "hub")).status, 401)

    async def test_bonuses_once_and_reminders_shared_with_bot(self):
        before = db.get_user(self.uid)
        with patch("webapp_experience.get_daily_bonus", return_value=17), patch(
                "webapp_experience.get_weekly_bonus", return_value=29):
            for kind in ("daily", "weekly"):
                first = await self.request("POST", "bonuses/claim", json={"kind": kind})
                self.assertTrue((await first.json())["claimed"])
                second = await self.request("POST", "bonuses/claim", json={"kind": kind})
                self.assertFalse((await second.json())["claimed"])
        after = db.get_user(self.uid)
        self.assertEqual(after["balance"], before["balance"] + 46)
        self.assertEqual(after["xp"], before["xp"] + 65)
        response = await self.request("PATCH", "bonuses/reminders", json={"daily": False})
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())["daily"]["reminder_enabled"])
        self.assertEqual(db.get_user(self.uid)["weekly_reminder_enabled"], 1)
        for value in ({"daily": 0}, {"admin": True}, {}):
            self.assertEqual((await self.request("PATCH", "bonuses/reminders", json=value)).status, 400)
        self.assertEqual((await self.request("POST", "bonuses/claim", json={"kind": []})).status, 400)

    async def test_preferences_favorites_are_partial_and_owned(self):
        values = {"bio": "<Анна>", "saved_bet": 245, "theme": "light", "hide_stats": True}
        self.assertEqual((await self.request("PATCH", "preferences", json=values)).status, 200)
        self.assertEqual((await self.request("PATCH", "preferences", json={"theme": "dark"})).status, 200)
        for _ in range(2):
            self.assertEqual((await self.request("PUT", "favorites", json={"game_id": "mines", "enabled": True})).status, 200)
        prefs = (await (await self.request("GET", "profile")).json())["preferences"]
        self.assertEqual(prefs["bio"], values["bio"])
        self.assertEqual(prefs["saved_bet"], 245)
        self.assertEqual(prefs["favorites"], ["mines"])
        self.assertEqual(db.get_player_preferences(self.other)["favorites"], [])
        for value in ({"saved_bet": True}, {"bio": "x" * 201}, {"is_admin": True}, []):
            self.assertEqual((await self.request("PATCH", "preferences", json=value)).status, 400)
        self.assertEqual((await self.request("PUT", "favorites", json={"game_id": {}, "enabled": True})).status, 400)

    async def test_custom_gif_is_private_validated_and_retrieved_without_telegram(self):
        response = await self.request("PUT", "profile/avatar", data=GIF)
        self.assertEqual(response.status, 200)
        with patch("webapp_routes.get_avatar") as telegram:
            response = await self.request("GET", "profile/avatar")
            self.assertEqual(await response.read(), GIF)
            self.assertEqual(response.content_type, "image/gif")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            telegram.assert_not_called()
        self.assertIsNone(db.get_custom_avatar(self.other))
        self.assertEqual((await self.request("PUT", "profile/avatar", data=b"GIF89a broken")).status, 400)
        self.assertEqual(db.get_custom_avatar(self.uid)["data"], GIF)
        self.assertEqual((await self.request("PUT", "profile/avatar", data=b"x" * (2 * 1024 * 1024 + 1))).status, 413)
        self.assertEqual((await self.request("DELETE", "profile/avatar")).status, 200)
        self.assertIsNone(db.get_custom_avatar(self.uid))

    async def test_history_snapshot_filters_export_and_identity(self):
        for n in range(24):
            db.add_balance(self.uid, 1, "daily", "own-" + str(n))
        db.add_balance(self.other, 5, "daily", "OUTSIDER")
        first = await (await self.request("GET", "history?category=bonuses&user_id=" + str(self.other))).json()
        second_path = "history?category=bonuses&page=1&anchor=" + str(first["anchor"])
        second = await (await self.request("GET", second_path)).json()
        db.add_balance(self.uid, 4, "daily", "NEW")
        again = await (await self.request("GET", second_path)).json()
        self.assertEqual(second, again)
        self.assertFalse({r["id"] for r in first["transactions"]} & {r["id"] for r in second["transactions"]})
        for path in ("history?category=evil", "history?page=-1", "history?anchor=-1", "history?anchor=9999999999999999999999"):
            self.assertEqual((await self.request("GET", path)).status, 400)
        db.add_balance(self.uid, 1, "promo", "=BAD()")
        response = await self.request("GET", "history/export")
        csv = await response.text()
        self.assertNotIn("OUTSIDER", csv)
        self.assertIn("'=BAD()", csv)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_coinflip_response_loss_retry_conflict_and_server_randomness(self):
        before = db.get_user(self.uid)["balance"]
        body = {"request_id": "a" * 32, "bet": 100, "choice": "орёл", "result": "решка"}
        with patch("webapp_experience.secrets.choice", return_value="орёл"), patch(
                "webapp_experience.check_achievements") as achievements:
            first = await (await self.request("POST", "coinflip", json=body)).json()
            self.assertTrue(first["round"]["won"])
            self.assertEqual(first["balance"], before + 85)
            registry.register(self.uid, "joker", object())
            repeated = await self.request("POST", "coinflip", json=body)
            self.assertEqual(repeated.status, 200)
            self.assertFalse((await repeated.json())["round"]["fresh"])
            achievements.assert_called_once_with(self.uid)
            conflict = {**body, "bet": 200}
            self.assertEqual((await self.request("POST", "coinflip", json=conflict)).status, 409)
            fresh = {**body, "request_id": "b" * 32}
            self.assertEqual((await self.request("POST", "coinflip", json=fresh)).status, 409)
        self.assertEqual(db.get_stats(self.uid)["total_games"], 1)
        self.assertEqual(db.get_user(self.uid)["balance"], before + 85)

    async def test_bad_coinflip_body_and_insufficient_balance_do_not_charge(self):
        before = db.get_user(self.uid)["balance"]
        valid = {"request_id": "a" * 32, "bet": 100, "choice": "орёл"}
        for body in ([], {**valid, "bet": True}, {**valid, "request_id": []}, {**valid, "choice": "edge"}):
            self.assertEqual((await self.request("POST", "coinflip", json=body)).status, 400)
        self.assertEqual((await self.request("POST", "coinflip", json={**valid, "bet": before + 1})).status, 402)
        self.assertEqual(db.get_user(self.uid)["balance"], before)

    async def test_statistics_and_period_rank_validate_queries_and_privacy(self):
        db.play_coinflip(self.uid, "c" * 32, 100, "орёл", "орёл")
        data = await (await self.request("GET", "statistics?days=7&user_id=" + str(self.other))).json()
        self.assertEqual(data["summary"]["games"], 1)
        self.assertEqual(data["summary"]["net"], 85)
        self.assertEqual(data["points"][-1]["balance"], db.get_user(self.uid)["balance"])
        rank = await (await self.request("GET", "leaderboard?mode=wins&period=week")).json()
        self.assertIsNotNone(rank["my_rank"])
        db.set_player_preferences(self.uid, {"hide_stats": True})
        rank = await (await self.request("GET", "leaderboard?mode=wins&period=week")).json()
        self.assertIsNone(rank["my_rank"])
        self.assertFalse(any(p["user_id"] == self.uid for p in rank["players"]))
        for path in ("statistics?days=31", "leaderboard?mode=balance&period=week", "leaderboard?limit=10000", "leaderboard?mode=evil"):
            self.assertEqual((await self.request("GET", path)).status, 400)
