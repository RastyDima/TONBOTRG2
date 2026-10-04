from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.economy_views import HISTORY_LABELS, bonus_status


def bonuses_kb(user: dict) -> InlineKeyboardMarkup:
    status = bonus_status(user)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="☀️ Забрать ежедневный" if status["daily"] else "✅ Ежедневный получен",
            callback_data="daily" if status["daily"] else "bonuses",
        )],
        [InlineKeyboardButton(
            text="🗓 Забрать еженедельный" if status["weekly"] else "✅ Еженедельный получен",
            callback_data="weekly" if status["weekly"] else "bonuses",
        )],
        [InlineKeyboardButton(text="🔔 Настроить напоминания", callback_data="reminders")],
        [InlineKeyboardButton(text="◀ Главное меню", callback_data="menu")],
    ])


def reminders_kb(user: dict) -> InlineKeyboardMarkup:
    rows = []
    for kind, label in (("daily", "Ежедневные"), ("weekly", "Еженедельные")):
        enabled = bool(user.get(f"{kind}_reminder_enabled", 1))
        rows.append([InlineKeyboardButton(
            text=f"{'🔔' if enabled else '🔕'} {label}: {'ВКЛ' if enabled else 'ВЫКЛ'}",
            callback_data=f"reminder:{kind}:{int(not enabled)}",
        )])
    rows.append([InlineKeyboardButton(text="◀ К бонусам", callback_data="bonuses")])
    rows.append([InlineKeyboardButton(text="◀ Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_kb(category: str, page: int, pages: int, anchor: int) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(
        text=f"{'✓ ' if key == category else ''}{label}",
        callback_data=f"history:{key}:0:{anchor}",
    ) for key, label in HISTORY_LABELS.items()]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"history:{category}:{page - 1}:{anchor}"))
    navigation.append(InlineKeyboardButton(text=f"{page + 1} / {pages}", callback_data="history_page"))
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton(text="Далее ▶", callback_data=f"history:{category}:{page + 1}:{anchor}"))
    rows.append(navigation)
    rows.append([InlineKeyboardButton(text="↻ Обновить", callback_data=f"history_refresh:{category}")])
    rows.append([InlineKeyboardButton(text="◀ Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
