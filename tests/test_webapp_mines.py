"""HTTP regression checks for authenticated WebApp Mines."""

import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

_scratch = tempfile.TemporaryDirectory()
os.environ.setdefault("BOT_TOKEN", "offline-webapp-tests")
os.environ.setdefault("RENDER", "false")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("DATABASE_PATH", str(Path(_scratch.name) / "webapp-tests.db"))
os.environ.setdefault("ADMIN_PANEL_PASSWORD", "offline-webapp-tests")
os.environ.setdefault("WEBHOOK_SECRET", "offline-webapp-tests")

from config import BOT_TOKEN  # noqa: E402
from database import db  # noqa: E402
from mobile_pairing import claim_pairing  # noqa: E402
from handlers.start import cmd_start  # noqa: E402
from utils.game_registry import registry  # noqa: E402
from webapp_auth import issue_session_token, verify_session_token  # noqa: E402
from webapp_routes import register_webapp_routes  # noqa: E402


def telegram_init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class WebappMinesTests(unittest.IsolatedAsyncioTestCase):
    next_user_id = 8830000

    async def asyncSetUp(self):
        type(self).next_user_id += 1
        self.user_id = type(self).next_user_id
        db.register_user(self.user_id, None, "Webapp Test")
        self.before = db.get_user(self.user_id)["balance"]
        app = web.Application()
        register_webapp_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer " + issue_session_token(self.user_id)}

    async def asyncTearDown(self):
        registry.release(self.user_id)
        await self.client.close()

    async def post(self, path, body, headers=None):
        return await self.client.post(path, json=body, headers=headers or self.headers)

    async def start_round(self, bet=100, mine_count=3):
        response = await self.post("/app/api/mines/start", {"bet": bet, "mine_count": mine_count})
        self.assertEqual(response.status, 200)
        return await response.json()

    async def test_signed_session_rejects_forgery_and_query_token(self):
        forged = json.dumps({"user_id": self.user_id})
        response = await self.client.get(
            "/app/api/profile", headers={"Authorization": "Bearer " + forged}
        )
        self.assertEqual(response.status, 401)
        response = await self.client.get(
            "/app/api/profile?token=" + issue_session_token(self.user_id)
        )
        self.assertEqual(response.status, 401)
        token = issue_session_token(self.user_id)
        self.assertEqual(verify_session_token(token), self.user_id)
        payload, signature = token.split(".")
        forged_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        self.assertIsNone(verify_session_token(payload + "." + forged_signature))
        with patch("webapp_auth.time.time", return_value=time.time() + 86401):
            self.assertIsNone(verify_session_token(token))

    async def test_telegram_auth_issues_opaque_session(self):
        response = await self.client.post(
            "/app/api/auth", json={"initData": telegram_init_data(self.user_id)}
        )
        self.assertEqual(response.status, 200)
        token = (await response.json())["token"]
        self.assertIn(".", token)
        self.assertEqual(verify_session_token(token), self.user_id)
        response = await self.client.get(
            "/app/api/profile", headers={"Authorization": "Bearer " + token}
        )
        self.assertEqual(response.status, 200)

    async def test_android_pairing_uses_bot_identity_once(self):
        response = await self.client.post("/app/api/mobile/pair/start")
        self.assertEqual(response.status, 200)
        pairing = await response.json()
        self.assertNotEqual(pairing["code"], pairing["request_id"])
        self.assertIn("?start=app_" + pairing["code"], pairing["bot_url"])

        response = await self.post("/app/api/mobile/pair/complete", {
            "request_id": pairing["request_id"],
        })
        self.assertEqual(response.status, 202)
        self.assertFalse(claim_pairing(pairing["request_id"], self.user_id))
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=self.user_id, username=None, first_name="Test"),
            text="/start app_" + pairing["code"],
            answer=AsyncMock(),
        )
        await cmd_start(message)
        message.answer.assert_awaited_once()
        self.assertIn("Аккаунт подключён", message.answer.await_args.args[0])
        self.assertFalse(claim_pairing(pairing["code"], self.user_id + 1))

        response = await self.post("/app/api/mobile/pair/complete", {
            "request_id": pairing["request_id"],
        })
        self.assertEqual(response.status, 200)
        token = (await response.json())["token"]
        self.assertEqual(verify_session_token(token), self.user_id)
        with patch("webapp_auth.time.time", return_value=time.time() + 2 * 86400):
            self.assertEqual(verify_session_token(token), self.user_id)
        with patch("webapp_auth.time.time", return_value=time.time() + 31 * 86400):
            self.assertIsNone(verify_session_token(token))
        response = await self.client.get(
            "/app/api/profile", headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(response.status, 200)
        response = await self.post("/app/api/mobile/pair/complete", {
            "request_id": pairing["request_id"],
        })
        self.assertEqual(response.status, 410)

    async def test_start_reveal_cashout_and_repeated_cashout(self):
        data = await self.start_round()
        round_data = data["round"]
        self.assertEqual(data["balance"], self.before - 100)
        self.assertIsNone(round_data["mines"])
        self.assertIsNone(round_data["seed"])
        self.assertTrue(round_data["seed_hash"])
        response = await self.client.get("/app/api/mines", headers=self.headers)
        self.assertEqual((await response.json())["round"]["id"], round_data["id"])

        game = registry.game(self.user_id)
        safe_index = next(index for index in range(25) if index not in game.mine_positions)
        response = await self.post("/app/api/mines/reveal", {
            "round_id": round_data["id"], "index": safe_index,
        })
        self.assertEqual(response.status, 200)
        revealed = (await response.json())["round"]
        self.assertIn(safe_index, revealed["opened"])
        self.assertTrue(revealed["can_cashout"])

        response = await self.post("/app/api/mines/cashout", {"round_id": round_data["id"]})
        self.assertEqual(response.status, 200)
        finished = await response.json()
        self.assertEqual(finished["round"]["status"], "won")
        self.assertEqual(
            hashlib.sha256(finished["round"]["seed"].encode()).hexdigest(),
            round_data["seed_hash"],
        )
        self.assertEqual(db.get_user(self.user_id)["balance"], finished["balance"])
        self.assertEqual(finished["balance"], self.before - 100 + finished["round"]["payout"])
        self.assertEqual(db.get_stats(self.user_id)["wins"], 1)
        response = await self.post("/app/api/mines/cashout", {"round_id": round_data["id"]})
        self.assertEqual(response.status, 409)
        self.assertEqual(db.get_user(self.user_id)["balance"], finished["balance"])

    async def test_loss_and_old_round_id_cannot_be_replayed(self):
        data = await self.start_round()
        round_id = data["round"]["id"]
        game = registry.game(self.user_id)
        mine = next(iter(game.mine_positions))
        response = await self.post("/app/api/mines/reveal", {
            "round_id": "wrong-round", "index": mine,
        })
        self.assertEqual(response.status, 409)
        self.assertEqual(game.safe_revealed, 0)
        response = await self.post("/app/api/mines/reveal", {
            "round_id": round_id, "index": mine,
        })
        self.assertEqual(response.status, 200)
        finished = (await response.json())["round"]
        self.assertEqual(finished["status"], "lost")
        self.assertEqual(finished["exploded"], mine)
        self.assertIn(mine, finished["mines"])
        self.assertEqual(db.get_user(self.user_id)["balance"], self.before - 100)
        self.assertEqual(db.get_stats(self.user_id)["losses"], 1)
        response = await self.post("/app/api/mines/reveal", {
            "round_id": round_id, "index": mine,
        })
        self.assertEqual(response.status, 409)

    async def test_cancel_refunds_only_before_first_reveal(self):
        data = await self.start_round()
        response = await self.post("/app/api/mines/cancel", {
            "round_id": data["round"]["id"],
        })
        self.assertEqual((await response.json())["round"]["status"], "cancelled")
        self.assertEqual(db.get_user(self.user_id)["balance"], self.before)

        data = await self.start_round()
        game = registry.game(self.user_id)
        safe = next(index for index in range(25) if index not in game.mine_positions)
        await self.post("/app/api/mines/reveal", {
            "round_id": data["round"]["id"], "index": safe,
        })
        response = await self.post("/app/api/mines/cancel", {
            "round_id": data["round"]["id"],
        })
        self.assertEqual((await response.json())["round"]["status"], "lost")
        self.assertEqual(db.get_user(self.user_id)["balance"], self.before - 100)

    async def test_invalid_bets_and_unauthorized_start(self):
        for body in ({"bet": True, "mine_count": 3}, {"bet": 250001, "mine_count": 3},
                     {"bet": 100, "mine_count": 11}):
            response = await self.post("/app/api/mines/start", body)
            self.assertEqual(response.status, 400)
        response = await self.post(
            "/app/api/mines/start", {"bet": 100, "mine_count": 3},
            headers={"Authorization": "Bearer " + json.dumps({"user_id": self.user_id})},
        )
        self.assertEqual(response.status, 401)
        self.assertEqual(db.get_user(self.user_id)["balance"], self.before)
