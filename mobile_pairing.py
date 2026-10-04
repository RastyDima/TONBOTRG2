"""Short-lived, one-time Telegram bot pairing for the Android app."""

import secrets
import time


PAIRING_TTL = 600
MAX_PENDING = 2000

_requests: dict[str, dict] = {}
_codes: dict[str, str] = {}


def _prune() -> None:
    now = time.time()
    for request_id, request in list(_requests.items()):
        if request["expires_at"] <= now:
            _requests.pop(request_id, None)
            _codes.pop(request["code"], None)


def create_pairing(device_label: str = "Android-устройство") -> dict | None:
    """Return a private poll ID and a separate code for the bot deep link."""
    _prune()
    if len(_requests) >= MAX_PENDING:
        return None
    request_id = secrets.token_urlsafe(24)
    code = secrets.token_urlsafe(9)
    expires_at = int(time.time() + PAIRING_TTL)
    _requests[request_id] = {
        "code": code,
        "user_id": None,
        "expires_at": expires_at,
        "device_label": device_label,
    }
    _codes[code] = request_id
    return {"request_id": request_id, "code": code, "expires_at": expires_at}


def claim_pairing(code: str, user_id: int) -> bool:
    """Confirm a code from a Telegram message sent by the account owner."""
    if not isinstance(code, str) or type(user_id) is not int or user_id <= 0:
        return False
    _prune()
    request_id = _codes.pop(code, None)
    if request_id is None:
        return False
    request = _requests.get(request_id)
    if request is None or request["user_id"] is not None:
        return False
    request["user_id"] = user_id
    return True


def consume_pairing(request_id: str) -> tuple[str, int | None, str | None]:
    """Return pending, claimed or expired; a claimed identity is returned once."""
    if not isinstance(request_id, str) or len(request_id) > 128:
        return "expired", None, None
    _prune()
    request = _requests.get(request_id)
    if request is None:
        return "expired", None, None
    if request["user_id"] is None:
        return "pending", None, None
    _requests.pop(request_id, None)
    _codes.pop(request["code"], None)
    return "claimed", request["user_id"], request["device_label"]
