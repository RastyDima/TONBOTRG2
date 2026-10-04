"""Text and pagination shared by the bot's economy screens."""
from datetime import date, timedelta

from utils.helpers import format_number, history_text

HISTORY_PAGE_SIZE = 10
HISTORY_LABELS = {
    "all": "Все",
    "games": "Игры",
    "bonuses": "Бонусы",
    "transfers": "Переводы",
    "shop": "Магазин",
    "referrals": "Рефералы",
}


def bonus_status(user: dict, today: date | None = None) -> dict:
    today = today or date.today()
    year, week, _ = today.isocalendar()
    return {
        "daily": user.get("last_daily") != today.isoformat(),
        "weekly": user.get("last_weekly") != f"{year}-W{week:02d}",
        "next_daily": (today + timedelta(days=1)).strftime("%d.%m.%Y"),
        "next_weekly": (today + timedelta(days=7 - today.weekday())).strftime("%d.%m.%Y"),
    }


def bonuses_text(user: dict, daily_amount: int, weekly_amount: int, notice: str = "") -> str:
    status = bonus_status(user)
    daily = "🟢 Можно забрать" if status["daily"] else f"✅ Получен. Следующий: {status['next_daily']}"
    weekly = "🟢 Можно забрать" if status["weekly"] else f"✅ Получен. Следующий: {status['next_weekly']}"
    daily_reminder = "вкл." if user.get("daily_reminder_enabled", 1) else "выкл."
    weekly_reminder = "вкл." if user.get("weekly_reminder_enabled", 1) else "выкл."
    prefix = f"{notice}\n\n" if notice else ""
    return (
        f"🎁 <b>Бонусы</b>\n\n{prefix}"
        f"☀️ <b>Ежедневный — {format_number(daily_amount)} TON</b>\n{daily}\n\n"
        f"🗓 <b>Еженедельный — {format_number(weekly_amount)} TON</b>\n{weekly}\n\n"
        f"💳 Баланс: <b>{format_number(user['balance'])}</b> TON\n"
        f"🔔 Напоминания: ежедневные {daily_reminder}, еженедельные {weekly_reminder}\n\n"
        "Ежедневный бонус обновляется в полночь, недельный — в понедельник "
        "по времени сервера."
    )


def reminders_text(user: dict) -> str:
    daily = "включены" if user.get("daily_reminder_enabled", 1) else "выключены"
    weekly = "включены" if user.get("weekly_reminder_enabled", 1) else "выключены"
    return (
        "🔔 <b>Напоминания о бонусах</b>\n\n"
        f"☀️ Ежедневные: <b>{daily}</b>\n"
        f"🗓 Еженедельные: <b>{weekly}</b>\n\n"
        "Включайте каждый тип отдельно. Бот напоминает о доступном бонусе "
        "не чаще одного раза за период, если вы уже забирали его раньше.\n"
        "Отключение напоминаний не мешает получать бонусы."
    )


def history_page(database, user_id: int, category: str = "all", page: int = 0,
                 anchor: int | None = None) -> dict:
    if category not in HISTORY_LABELS or page < 0:
        raise ValueError("Invalid history page")
    if anchor is None:
        latest = database.get_transactions(user_id, limit=1)
        anchor = latest[0]["id"] if latest else 0
    total = database.count_transactions(user_id, category=category, before_id=anchor)
    pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    page = min(page, pages - 1)
    transactions = database.get_transactions(
        user_id, limit=HISTORY_PAGE_SIZE, offset=page * HISTORY_PAGE_SIZE,
        category=category, before_id=anchor,
    )
    return {
        "text": history_text(transactions, category=HISTORY_LABELS[category],
                             page=page, pages=pages, total=total),
        "category": category, "page": page, "pages": pages, "anchor": anchor,
    }
