"""Send bonus reminders while respecting each player's saved preferences."""
from utils.helpers import format_number


async def send_bonus_reminders(database, send, daily_amount, weekly_amount, markup_factory):
    for kind, amount, title in (
        ("daily", daily_amount, "🎁 Ежедневный"),
        ("weekly", weekly_amount, "🗓 Еженедельный"),
    ):
        eligible = database.get_daily_eligible if kind == "daily" else database.get_weekly_eligible
        mark = database.mark_daily_notified if kind == "daily" else database.mark_weekly_notified
        for recipient in eligible():
            # Preferences may change while another player's message is being sent.
            user = database.get_user(recipient["id"])
            if not user or user["is_blocked"] or not user.get(f"{kind}_reminder_enabled", 1):
                continue
            delivered = await send(
                user["id"],
                f"<b>{title} бонус доступен!</b>\n\n"
                f"Заберите {format_number(amount)} TON, нажав кнопку ниже.",
                markup_factory(kind),
            )
            if delivered:
                mark(user["id"])
