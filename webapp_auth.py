"""Telegram Mini App initData validation."""
import hashlib
import hmac
import json
import time
import urllib.parse
import base64
import binascii

from config import BOT_TOKEN
from database import db

TELEGRAM_AUTH_TTL = 86400  # 24 hours
SESSION_TTL = 86400
MOBILE_SESSION_TTL = 30 * 86400


def _session_key() -> bytes:
    return hmac.new(BOT_TOKEN.encode(), b"TonCasinoWebSessionV2", hashlib.sha256).digest()


def issue_session_token(user_id: int, mobile: bool = False,
                        session_id: str | None = None, expires_at: int | None = None) -> str:
    if mobile and not session_id:
        raise ValueError("mobile tokens require a stored session")
    payload = json.dumps(
        {"uid": int(user_id), "exp": expires_at if expires_at is not None else int(time.time()) +
         (MOBILE_SESSION_TTL if mobile else SESSION_TTL),
         "kind": "mobile" if mobile else "web", **({"sid": session_id} if mobile else {})},
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(_session_key(), encoded.encode(), hashlib.sha256).digest()
    return encoded + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def verify_session(token: str) -> dict | None:
    if not isinstance(token, str) or len(token) > 512:
        return None
    try:
        encoded, signature = token.split(".")
        expected = hmac.new(_session_key(), encoded.encode(), hashlib.sha256).digest()
        received = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, received):
            return None
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if not isinstance(payload, dict):
            return None
        user_id, expires, kind = payload.get("uid"), payload.get("exp"), payload.get("kind")
        if type(user_id) is not int or user_id <= 0 or type(expires) is not int:
            return None
        if kind not in ("web", "mobile"):
            return None
        now = int(time.time())
        ttl = MOBILE_SESSION_TTL if kind == "mobile" else SESSION_TTL
        if not now < expires <= now + ttl:
            return None
        if kind == "web":
            return {"user_id": user_id, "session_id": None, "kind": "web"}
        session_id = payload.get("sid")
        if not isinstance(session_id, str) or not 16 <= len(session_id) <= 128:
            return None
        session = db.get_mobile_session(session_id)
        if (not session or session["user_id"] != user_id or session["revoked_at"] is not None
                or session["expires_at"] <= now or session["expires_at"] != expires):
            return None
        if session["last_seen_at"] <= now - 300:
            db.touch_mobile_session(session_id, now)
        return {"user_id": user_id, "session_id": session_id, "kind": "mobile"}
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error):
        return None


def verify_session_token(token: str) -> int | None:
    session = verify_session(token)
    return session["user_id"] if session else None


def validate_telegram_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData.

    Returns parsed user dict on success, None on failure.
    """
    if not isinstance(init_data, str) or not init_data or len(init_data) > 8192:
        return None

    parsed = dict(urllib.parse.parse_qsl(init_data))
    if "hash" not in parsed:
        return None

    received_hash = parsed.pop("hash")
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )

    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    try:
        auth_date = int(parsed.get("auth_date", 0))
    except (TypeError, ValueError):
        return None
    if not 0 <= time.time() - auth_date <= TELEGRAM_AUTH_TTL:
        return None

    try:
        user = json.loads(parsed.get("user", "{}"))
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
        return None

    return user
