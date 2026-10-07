import os
import secrets
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required — never hardcode secrets")

ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]

DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "bot.db"))

DATABASE_URL = os.getenv("DATABASE_URL") or None
if not DATABASE_URL and os.getenv("RENDER", "").lower() == "true":
    DATABASE_URL = "postgresql://u_tenant_18451181:qw654321rty1@db.armordb.org:6432/db_tenant_9eb5a222"

if os.getenv("RENDER", "").lower() == "true":
    PUBLIC_BASE_URL = (
        os.getenv("RENDER_EXTERNAL_URL")
        or f"https://{os.getenv('RENDER_SERVICE_NAME', 'tonbotrg')}.onrender.com"
    )
else:
    PUBLIC_BASE_URL = ""

ADMIN_PANEL_USER = os.getenv("ADMIN_PANEL_USER", "admin")
ADMIN_PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD")
if not ADMIN_PANEL_PASSWORD:
    ADMIN_PANEL_PASSWORD = secrets.token_urlsafe(16)
    log.warning("ADMIN_PANEL_PASSWORD not set — generated a temporary password")

WEBHOOK_URL = os.getenv("WEBHOOK_URL") or None
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
if not WEBHOOK_SECRET:
    WEBHOOK_SECRET = secrets.token_urlsafe(32)
    log.warning("WEBHOOK_SECRET not set — generated a temporary secret")
PORT = int(os.getenv("PORT", "8080"))

if os.getenv("RENDER", "").lower() == "true" and not WEBHOOK_URL:
    WEBHOOK_URL = PUBLIC_BASE_URL

STARTING_BALANCE = 1000
DAILY_BONUS = 1000
WEEKLY_BONUS = 5000

MIN_BET = 1
MAX_BET = 250_000
MAX_GAME_MULTIPLIER = 8.0

BOT_USERNAME = os.getenv("BOT_USERNAME", "tonbotgram_bot").lstrip("@")
