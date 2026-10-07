"""Authenticated bonuses, history, player preferences and instant games."""
import asyncio
import logging
import secrets
from datetime import datetime, time, timedelta

from aiohttp import web

from database import db
from utils.achievements import check_achievements
from utils.avatar_uploads import validate_avatar
from utils.avatars import MAX_IMAGE_BYTES
from utils.economy_views import bonus_status, history_page
from utils.game_registry import award_progress, registry
from utils.helpers import get_daily_bonus, get_weekly_bonus
from utils.player_data import GAMES
from utils.player_views import history_csv

log = logging.getLogger(__name__)


def bonuses_data(user):
    status = bonus_status(user)
    today = datetime.now().date()
    midnight = datetime.combine(today + timedelta(days=1), time.min)
    monday = datetime.combine(today + timedelta(days=7 - today.weekday()), time.min)
    return {"daily": {"amount": get_daily_bonus(), "available": status["daily"],
                      "reminder_enabled": bool(user.get("daily_reminder_enabled", 1)), "next_at": midnight.isoformat()},
            "weekly": {"amount": get_weekly_bonus(), "available": status["weekly"],
                       "reminder_enabled": bool(user.get("weekly_reminder_enabled", 1)), "next_at": monday.isoformat()},
            "balance": user["balance"]}


def register_player_routes(app, auth_user):
    def json(data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    async def body(request):
        try:
            value = await request.json()
            if isinstance(value, dict):
                return value
        except (ValueError, web.HTTPException):
            pass
        raise web.HTTPBadRequest(text='{"error":"bad request"}', content_type="application/json")

    async def hub(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        entry = registry.get(user["id"])
        active = {"type": entry["type"], "name": GAMES.get(entry["type"], {}).get("name", "Игра")} if entry else None
        return json({"bonuses": bonuses_data(user), "active_game": active,
                     "preferences": db.get_player_preferences(user["id"]),
                     "games": [{"id": key, **value, "web_available": key in ("mines", "coinflip")} for key, value in GAMES.items()]})

    async def bonuses(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        return json(bonuses_data(user))

    async def claim(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        value = await body(request)
        kind = value.get("kind")
        if kind not in ("daily", "weekly"):
            return json({"error": "invalid bonus"}, 400)
        amount = get_daily_bonus() if kind == "daily" else get_weekly_bonus()
        claimed = (db.claim_daily if kind == "daily" else db.claim_weekly)(user["id"], amount)
        if claimed:
            award_progress(user["id"], 15 if kind == "daily" else 50)
        return json({"claimed": claimed, "amount": amount if claimed else 0,
                     "bonuses": bonuses_data(db.get_user(user["id"]))})

    async def reminders(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        value = await body(request)
        if not value or not set(value) <= {"daily", "weekly"} or any(type(enabled) is not bool for enabled in value.values()):
            return json({"error": "invalid reminders"}, 400)
        for kind, enabled in value.items():
            db.set_bonus_reminder(user["id"], kind, enabled)
        return json(bonuses_data(db.get_user(user["id"])))

    async def history(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        try:
            page = int(request.query.get("page", "0"))
            anchor = int(request.query["anchor"]) if "anchor" in request.query else None
            if anchor is not None and not 0 <= anchor <= 2 ** 63 - 1:
                raise ValueError()
            view = history_page(db, user["id"], request.query.get("category", "all"), page, anchor)
        except (ValueError, OverflowError):
            return json({"error": "invalid history page"}, 400)
        return json({key: value for key, value in view.items() if key != "text"})

    async def history_export(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        return web.Response(body=history_csv(db, user["id"]), content_type="text/csv",
                            headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="ton-history.csv"'})

    async def preferences(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        try:
            db.set_player_preferences(user["id"], await body(request))
        except ValueError:
            return json({"error": "invalid preferences"}, 400)
        return json(db.get_player_preferences(user["id"]))

    async def favorite(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        value = await body(request)
        try:
            db.set_favorite(user["id"], value.get("game_id"), value.get("enabled"))
        except (ValueError, TypeError):
            return json({"error": "invalid favorite"}, 400)
        return json(db.get_player_preferences(user["id"]))

    async def avatar_upload(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        if request.content_length and request.content_length > MAX_IMAGE_BYTES:
            return json({"error": "avatar too large"}, 413)
        data = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            data.extend(chunk)
            if len(data) > MAX_IMAGE_BYTES:
                return json({"error": "avatar too large"}, 413)
        try:
            content_type = await asyncio.to_thread(validate_avatar, bytes(data))
        except ValueError:
            return json({"error": "invalid avatar"}, 400)
        db.set_custom_avatar(user["id"], bytes(data), content_type)
        return json({"ok": True, "content_type": content_type})

    async def avatar_delete(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        db.delete_custom_avatar(user["id"])
        return json({"ok": True})

    async def statistics(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        try:
            return json(db.player_statistics(user["id"], int(request.query.get("days", "30"))))
        except (ValueError, OverflowError):
            return json({"error": "invalid statistics period"}, 400)

    async def coinflip(request):
        user = await auth_user(request)
        if not user:
            return json({"error": "unauthorized"}, 401)
        value = await body(request)
        # Retrying an already committed round remains possible during another game.
        request_id = value.get("request_id")
        if not isinstance(request_id, str) or len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
            return json({"error": "invalid coinflip"}, 400)
        entry = registry.get(user["id"])
        if entry:
            with db._player_cursor() as cur:
                cur.execute(db._player_sql("SELECT request_id FROM instant_rounds WHERE user_id = ? AND request_id = ?"), (user["id"], request_id))
                if not cur.fetchone():
                    return json({"error": "active game"}, 409)
        try:
            receipt = db.play_coinflip(user["id"], value.get("request_id"), value.get("bet"),
                                       value.get("choice"), secrets.choice(("орёл", "решка")))
        except ValueError:
            return json({"error": "invalid coinflip"}, 400)
        if "error" in receipt:
            return json(receipt, 402 if receipt["error"] == "insufficient balance" else 409)
        if receipt["fresh"]:
            try:
                check_achievements(user["id"])
            except Exception:
                log.error("Achievement check failed after coinflip")
        return json({"round": receipt, "balance": db.get_user(user["id"])["balance"]})

    for method, path, handler in [
        ("GET", "hub", hub), ("GET", "bonuses", bonuses), ("POST", "bonuses/claim", claim),
        ("PATCH", "bonuses/reminders", reminders), ("GET", "history", history),
        ("GET", "history/export", history_export), ("PATCH", "preferences", preferences),
        ("PUT", "favorites", favorite), ("PUT", "profile/avatar", avatar_upload),
        ("DELETE", "profile/avatar", avatar_delete), ("GET", "statistics", statistics),
        ("POST", "coinflip", coinflip),
    ]:
        app.router.add_route(method, "/app/api/" + path, handler)
