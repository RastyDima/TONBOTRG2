"""WebApp API routes for Telegram Mini App."""
import logging
import re
import time
from pathlib import Path

from aiohttp import web

from config import BOT_USERNAME, MAX_BET, MAX_GAME_MULTIPLIER, MIN_BET
from database import db
from games.mines import FIELD_SIZE, MAX_MINES, MIN_MINES, MinesGame
from handlers.shop import SHOP_ITEMS, FRAME_BY_ID, TITLE_BY_ID, ALL_BY_ID
from mobile_pairing import consume_pairing, create_pairing
from utils.achievements import ACHIEVEMENTS
from utils.game_registry import cancel_game, cashout_game, lose_game, registry
from webapp_auth import (MOBILE_SESSION_TTL, issue_session_token,
                         validate_telegram_init_data, verify_session)

logger = logging.getLogger(__name__)

WEBAPP_API_PREFIX = "/app"
WEBAPP_STATIC_DIR = Path(__file__).parent / "webapp"


def _json_response(data, status=200):
    return web.json_response(data, status=status)


async def _auth_principal(request):
    """Return an authenticated user and token metadata, or None."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    session = verify_session(token)
    if session is None:
        return None
    user = db.get_user(session["user_id"])
    if not user or user.get("is_blocked"):
        return None
    return user, session


async def _auth_user(request):
    principal = await _auth_principal(request)
    return principal[0] if principal else None


def _device_label(user_agent: str) -> str:
    match = re.search(r"TonCasinoAndroid/[0-9.]+ \(([^)]{1,80})\)", user_agent)
    if not match:
        return "Android-устройство"
    label = re.sub(r"[\x00-\x1f<>]", "", match.group(1)).strip()[:80]
    return label or "Android-устройство"


def _mines_snapshot(game: MinesGame, status: str | None = None) -> dict:
    status = status or ("won" if game.cashed_out else "lost" if game.lost else "playing")
    finished = status != "playing"
    opened = len(game.revealed)
    return {
        "id": game.public_id,
        "status": status,
        "bet": game.bet,
        "mine_count": game.mines,
        "opened": sorted(game.revealed),
        "safe_total": game.safe_total,
        "multiplier": 0 if status == "lost" else game.multiplier,
        "payout": game.payout if status in ("playing", "won") else 0,
        "can_cashout": status == "playing" and game.can_cashout,
        "can_refund": status == "playing" and game.can_refund,
        "next_chance": (
            round((FIELD_SIZE - game.mines - opened) / (FIELD_SIZE - opened) * 100, 1)
            if status == "playing" and opened < game.safe_total else None
        ),
        "mines": sorted(game.mine_positions) if finished else None,
        "exploded": getattr(game, "exploded", None) if finished else None,
        "seed": game.seed if finished else None,
        "seed_hash": game.seed_hash,
    }


def _mines_active(user_id: int, round_id: str | None = None) -> MinesGame | None:
    game = registry.game(user_id)
    if not game or game.type != "mines" or game.is_over:
        return None
    if round_id is not None and game.public_id != round_id:
        return None
    return game


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

        if not isinstance(body, dict):
            return _json_response({"error": "bad request"}, 400)
        init_data = body.get("initData", "")
        user_data = validate_telegram_init_data(init_data)
        if not user_data:
            return _json_response({"error": "invalid init data"}, 401)

        user_id = user_data["id"]
        username = (user_data.get("username") or "").lower() or None
        first_name = user_data.get("first_name", "")

        existing = db.get_user(user_id)
        if not existing:
            db.register_user(user_id, username, first_name)
        else:
            db.register_user(user_id, username, first_name)

        token = issue_session_token(user_id)
        return _json_response({"token": token, "user_id": user_id})

    # --- Android: pair a device by confirming a one-time code in the bot ---

    async def api_mobile_pair_start(request):
        pairing = create_pairing(_device_label(request.headers.get("User-Agent", "")))
        if pairing is None:
            return _json_response({"error": "pairing unavailable"}, 429)
        response = _json_response({
            "request_id": pairing["request_id"],
            "code": pairing["code"],
            "expires_at": pairing["expires_at"],
            "server_time": int(time.time()),
            "bot_url": f"https://t.me/{BOT_USERNAME}?start=app_{pairing['code']}",
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    async def api_mobile_pair_complete(request):
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)
        if not isinstance(body, dict):
            return _json_response({"error": "bad request"}, 400)
        status, user_id, device_label = consume_pairing(body.get("request_id"))
        if status == "expired":
            return _json_response({"error": "pairing expired"}, 410)
        if status == "pending":
            return _json_response({"status": "pending"}, 202)
        user = db.get_user(user_id)
        if not user or user.get("is_blocked"):
            return _json_response({"error": "account unavailable"}, 403)
        expires_at = int(time.time()) + MOBILE_SESSION_TTL
        session_id = db.create_mobile_session(user_id, device_label, expires_at)
        response = _json_response({
            "status": "complete",
            "token": issue_session_token(user_id, mobile=True,
                                         session_id=session_id, expires_at=expires_at),
            "user_id": user_id,
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    async def api_mobile_sessions(request):
        principal = await _auth_principal(request)
        if not principal:
            return _json_response({"error": "unauthorized"}, 401)
        user, current = principal
        sessions = db.list_mobile_sessions(user["id"])
        response = _json_response({"sessions": [
            {**session, "is_current": session["id"] == current["session_id"]}
            for session in sessions
        ]})
        response.headers["Cache-Control"] = "no-store"
        return response

    async def api_mobile_session_revoke(request):
        principal = await _auth_principal(request)
        if not principal:
            return _json_response({"error": "unauthorized"}, 401)
        session_id = request.match_info["session_id"]
        if len(session_id) > 128 or not db.revoke_mobile_session(principal[0]["id"], session_id):
            return _json_response({"error": "device not found"}, 404)
        return _json_response({"revoked": True})

    async def api_mobile_sessions_revoke_others(request):
        principal = await _auth_principal(request)
        if not principal:
            return _json_response({"error": "unauthorized"}, 401)
        count = db.revoke_other_mobile_sessions(principal[0]["id"],
                                                principal[1]["session_id"])
        return _json_response({"revoked": count})

    async def api_mobile_session_logout(request):
        principal = await _auth_principal(request)
        if not principal or principal[1]["session_id"] is None:
            return _json_response({"error": "unauthorized"}, 401)
        db.revoke_mobile_session(principal[0]["id"], principal[1]["session_id"])
        return _json_response({"revoked": True})

    # --- Real Mines: the server owns the board, bet and settlement ---

    async def api_mines_state(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)
        active = registry.get(user["id"])
        game = _mines_active(user["id"])
        return _json_response({
            "round": _mines_snapshot(game) if game else None,
            "other_game": active["type"] if active and not game else None,
            "balance": user["balance"],
            "max_bet": MAX_BET,
        })

    async def api_mines_start(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)
        if not isinstance(body, dict):
            return _json_response({"error": "bad request"}, 400)
        bet, mine_count = body.get("bet"), body.get("mine_count")
        if (type(bet) is not int or not MIN_BET <= bet <= MAX_BET
                or type(mine_count) is not int or not MIN_MINES <= mine_count <= MAX_MINES):
            return _json_response({"error": "invalid bet or mine count"}, 400)
        if registry.is_active(user["id"]):
            return _json_response({"error": "active game"}, 409)
        fresh_user = db.get_user(user["id"])
        if bet > fresh_user["balance"]:
            return _json_response({"error": "insufficient balance"}, 402)
        game = MinesGame(user["id"], bet, mine_count)
        if not registry.register(user["id"], "mines", game):
            return _json_response({"error": "active game"}, 409)
        try:
            spent = db.start_mines_round(game)
        except Exception:
            registry.release(user["id"])
            raise
        if not spent:
            registry.release(user["id"])
            if db.get_user(user["id"])["balance"] < bet:
                return _json_response({"error": "insufficient balance"}, 402)
            return _json_response({"error": "active game"}, 409)
        game.persisted = True
        return _json_response({
            "round": _mines_snapshot(game),
            "balance": db.get_user(user["id"])["balance"],
        })

    async def api_mines_reveal(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)
        if not isinstance(body, dict):
            return _json_response({"error": "bad request"}, 400)
        round_id, index = body.get("round_id"), body.get("index")
        if not isinstance(round_id, str) or type(index) is not int or not 0 <= index < FIELD_SIZE:
            return _json_response({"error": "invalid move"}, 400)
        game = _mines_active(user["id"], round_id)
        if not game:
            return _json_response({"error": "round not found"}, 409)
        if index in game.revealed:
            return _json_response({"error": "cell already opened", "round": _mines_snapshot(game)}, 409)
        if index in game.mine_positions:
            game.exploded = index
            lose_game(user["id"])
            return _json_response({
                "round": _mines_snapshot(game),
                "balance": db.get_user(user["id"])["balance"],
            })
        game.revealed.add(index)
        if not db.save_mines_round(game):
            registry.release(user["id"])
            return _json_response({"error": "round changed"}, 409)
        if game.safe_revealed == game.safe_total or game.multiplier >= MAX_GAME_MULTIPLIER:
            cashout_game(user["id"])
        return _json_response({
            "round": _mines_snapshot(game),
            "balance": db.get_user(user["id"])["balance"],
        })

    async def api_mines_cashout(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)
        round_id = body.get("round_id") if isinstance(body, dict) else None
        game = _mines_active(user["id"], round_id) if isinstance(round_id, str) else None
        if not game or not game.can_cashout:
            return _json_response({"error": "cashout unavailable"}, 409)
        cashout_game(user["id"])
        return _json_response({
            "round": _mines_snapshot(game),
            "balance": db.get_user(user["id"])["balance"],
        })

    async def api_mines_cancel(request):
        user = await _auth_user(request)
        if not user:
            return _json_response({"error": "unauthorized"}, 401)
        try:
            body = await request.json()
        except Exception:
            return _json_response({"error": "bad request"}, 400)
        round_id = body.get("round_id") if isinstance(body, dict) else None
        game = _mines_active(user["id"], round_id) if isinstance(round_id, str) else None
        if not game:
            return _json_response({"error": "round not found"}, 409)
        refunded = cancel_game(user["id"])
        return _json_response({
            "round": _mines_snapshot(game, "cancelled" if refunded else "lost"),
            "balance": db.get_user(user["id"])["balance"],
        })

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

        if not isinstance(body, dict):
            return _json_response({"error": "bad request"}, 400)
        item_id = body.get("item_id", "")
        if not isinstance(item_id, str):
            return _json_response({"error": "invalid item"}, 400)
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

        if not isinstance(body, dict):
            return _json_response({"error": "bad request"}, 400)
        item_id = body.get("item_id", "")
        if not isinstance(item_id, str):
            return _json_response({"error": "invalid item"}, 400)
        if item_id and (item_id not in ALL_BY_ID or not db.owns_item(user["id"], item_id)):
            return _json_response({"error": "item not owned"}, 403)
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
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mobile/pair/start", api_mobile_pair_start)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mobile/pair/complete", api_mobile_pair_complete)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/mobile/sessions", api_mobile_sessions)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mobile/sessions/revoke-others", api_mobile_sessions_revoke_others)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mobile/sessions/logout", api_mobile_session_logout)
    app.router.add_delete(f"{WEBAPP_API_PREFIX}/api/mobile/sessions/{{session_id}}", api_mobile_session_revoke)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/mines", api_mines_state)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mines/start", api_mines_start)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mines/reveal", api_mines_reveal)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mines/cashout", api_mines_cashout)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/mines/cancel", api_mines_cancel)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/profile", api_profile)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/profile/showcase", api_showcase_toggle)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/shop", api_shop)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/shop/buy", api_shop_buy)
    app.router.add_post(f"{WEBAPP_API_PREFIX}/api/shop/equip", api_shop_equip)
    app.router.add_get(f"{WEBAPP_API_PREFIX}/api/leaderboard", api_leaderboard)
