"""WebApp API routes for Telegram Mini App."""
import json
import logging
from pathlib import Path

from aiohttp import web

from database import db
from handlers.shop import SHOP_ITEMS, FRAME_BY_ID, TITLE_BY_ID, ALL_BY_ID
from utils.achievements import ACHIEVEMENTS
from webapp_auth import validate_telegram_init_data

logger = logging.getLogger(__name__)

WEBAPP_API_PREFIX = "/app"
WEBAPP_STATIC_DIR = Path(__file__).parent / "webapp"


def _json_response(data, status=200):
    return web.json_response(data, status=status)


async def _auth_user(request):
    """Extract and validate user from Bearer token. Returns user dict or None."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        token = request.query.get("token", "")
    if not token:
        return None
    try:
        payload = json.loads(token)
        user_id = payload.get("user_id")
        if not user_id:
            return None
        user = db.get_user(user_id)
        if not user or user.get("is_blocked"):
            return None
        return user
    except (json.JSONDecodeError, TypeError):
        return None


def register_webapp_routes(app: web.Application) -> None:
    """Register all WebApp routes on the aiohttp app."""

    # --- Static files ---
    app.router.add_static(
        f"{WEBAPP_API_PREFIX}/static",
        path=str(WEBAPP_STATIC_DIR),
        name="webapp_static",
    )

    # --- SPA entry point ---
    async def serve_index(request):
        index_path = str(WEBAPP_STATIC_DIR / "index.html")
        return web.FileResponse(index_path)

    app.router.add_get(f"{WEBAPP_API_PREFIX}/", serve_index)
    app.router.add_get(f"{WEBAPP_API_PREFIX}", serve_index)

    # --- Auth ---

    async def api_auth(request):
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)

        init_data = body.get("initData", "")
        user_data = validate_telegram_init_data(init_data)
        if not user_data:
            return _json_response({"error": "invalid init data"}, 401)

        user_id = user_data["id"]
        username = user_data.get("username", "").lower() or None
        first_name = user_data.get("first_name", "")

        existing = db.get_user(user_id)
        if not existing:
            db.register_user(user_id, username, first_name)
        else:
            db.register_user(user_id, username, first_name)

        token = json.dumps({"user_id": user_id})
        return _json_response({"token": token, "user_id": user_id})

    # --- Profile ---

    async def api_profile(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)

        stats = db.get_stats(user["id"])
        earned = set(db.get_achievements(user["id"]))
        showcase_ids = db.get_showcase(user["id"])
        awards = [
            {"id": award_id, "name": award["name"], "icon": award["icon"]}
            for award_id, award in ACHIEVEMENTS.items() if award_id in earned
        ]
        award_by_id = {award["id"]: award for award in awards}
        return _json_response({
            "user_id": user["id"],
            "username": user.get("username"),
            "first_name": user.get("first_name", ""),
            "balance": user.get("balance", 0),
            "rubies": user.get("rubies", 0),
            "xp": user.get("xp", 0),
            "active_frame": user.get("active_frame"),
            "active_title": user.get("active_title"),
            "total_games": stats.get("total_games", 0) if stats else 0,
            "wins": stats.get("wins", 0) if stats else 0,
            "losses": stats.get("losses", 0) if stats else 0,
            "total_bet": stats.get("total_bet", 0) if stats else 0,
            "total_won": stats.get("total_won", 0) if stats else 0,
            "referral_count": user.get("referral_count", 0),
            "earned_achievements": awards,
            "showcase": [award_by_id[award_id] for award_id in showcase_ids
                         if award_id in award_by_id],
        })

    async def api_showcase_toggle(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)
        if not isinstance(body, dict):
            return _json_response({"error": "bad request"}, 400)
        award_id = body.get("achievement_id")
        if not isinstance(award_id, str) or award_id not in ACHIEVEMENTS:
            return _json_response({"error": "invalid achievement"}, 400)
        result = db.toggle_showcase(user["id"], award_id)
        if result == "not_earned":
            return _json_response({"error": "not earned"}, 403)
        if result == "full":
            return _json_response({"error": "showcase full"}, 409)
        return _json_response({"ok": True, "result": result})

    # --- Shop ---

    async def api_shop(request):
        user = await _auth_user(request)
        user_id = user["id"] if user else 0

        frames = []
        for f in SHOP_ITEMS["frames"]:
            frames.append({
                "id": f["id"],
                "name": f["name"],
                "price": f["price"],
                "color": list(f["color"]),
                "owned": db.owns_item(user_id, f["id"]),
                "active": user.get("active_frame") == f["id"] if user else False,
            })

        titles = []
        for t in SHOP_ITEMS["titles"]:
            titles.append({
                "id": t["id"],
                "name": t["name"],
                "price": t["price"],
                "owned": db.owns_item(user_id, t["id"]),
                "active": user.get("active_title") == t["id"] if user else False,
            })

        exclusive = []
        for t in SHOP_ITEMS["exclusive_titles"]:
            exclusive.append({
                "id": t["id"],
                "name": t["name"],
                "owned": db.owns_item(user_id, t["id"]),
                "active": user.get("active_title") == t["id"] if user else False,
            })

        return _json_response({
            "balance": user.get("balance", 0) if user else 0,
            "frames": frames,
            "titles": titles,
            "exclusive_titles": exclusive,
        })

    async def api_shop_buy(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)

        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)

        item_id = body.get("item_id", "")
        item = ALL_BY_ID.get(item_id)
        if not item:
            return _json_response({"error": "item not found"}, 404)

        if db.owns_item(user["id"], item_id):
            return _json_response({"error": "already owned"}, 409)

        if user.get("balance", 0) < item["price"]:
            return _json_response({"error": "insufficient balance"}, 402)

        category = "frame" if item_id.startswith("frame") else "title"
        ok = db.buy_item(user["id"], item_id, category, item["price"])
        if not ok:
            return _json_response({"error": "purchase failed"}, 500)

        updated_user = db.get_user(user["id"])
        return _json_response({
            "ok": True,
            "balance": updated_user.get("balance", 0),
        })

    async def api_shop_equip(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)

        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)

        item_id = body.get("item_id", "")
        if item_id.startswith("frame"):
            db.set_active_frame(user["id"], item_id)
        elif item_id.startswith("title"):
            db.set_active_title(user["id"], item_id)
        elif item_id == "":
            category = body.get("category", "")
            if category == "frame":
                db.set_active_frame(user["id"], None)
            elif category == "title":
                db.set_active_title(user["id"], None)
        else:
            return _json_response({"error": "invalid item"}, 400)

        return _json_response({"ok": True})

    # --- Leaderboard ---

    async def api_leaderboard(request):
        user = await _auth_user(request)
        mode = request.query.get("mode", "balance")
        limit = min(int(request.query.get("limit", 20)), 50)

        if mode == "wins":
            top = db.top_wins(limit)
        elif mode == "xp":
            top = db.top_xp(limit)
        elif mode == "games":
            top = db.top_balance(limit)
        else:
            top = db.top_max_balance(limit)

        current_user_id = user["id"] if user else 0
        results = []
        for i, row in enumerate(top, 1):
            results.append({
                "rank": i,
                "user_id": row["id"],
                "username": row.get("username"),
                "first_name": row.get("first_name", "Игрок"),
                "balance": row.get("balance", 0),
                "max_balance": row.get("max_balance", 0),
                "wins": row.get("wins", 0) if "wins" in row else 0,
                "total_games": row.get("total_games", 0) if "total_games" in row else 0,
                "is_me": row["id"] == current_user_id,
            })

        my_rank = None
        if user:
            if mode == "wins":
                all_top = db.top_wins(1000)
            elif mode == "xp":
                all_top = db.top_xp(1000)
            elif mode == "games":
                all_top = db.top_balance(1000)
            else:
                all_top = db.top_max_balance(1000)
            for i, row in enumerate(all_top, 1):
                if row["id"] == current_user_id:
                    my_rank = i
                    break

        return _json_response({
            "mode": mode,
            "players": results,
            "my_rank": my_rank,
        })

    # Register API routes
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/auth", api_auth)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/profile", api_profile)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/profile/showcase", api_showcase_toggle)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/shop", api_shop)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/shop/buy", api_shop_buy)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/shop/equip", api_shop_equip)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/leaderboard", api_leaderboard)
