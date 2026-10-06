from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_admin: bool = False, user_id: int | None = None):
    rows = []
    if user_id is not None:
        from utils.game_registry import registry
        if registry.get(user_id):
            rows.append([InlineKeyboardButton(text="▶ Продолжить игру", callback_data="resume")])
    rows.append([
        InlineKeyboardButton(text="🎮 Игры", callback_data="menu_games"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
    ])
    rows.append([
        InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
        InlineKeyboardButton(text="🎁 Бонусы", callback_data="bonuses"),
    ])
    rows.append([
        InlineKeyboardButton(text="👥 Рефералы", callback_data="ref"),
        InlineKeyboardButton(text="🏆 Рейтинг", callback_data="rating"),
    ])
    rows.append([
        InlineKeyboardButton(text="📜 История", callback_data="history"),
        InlineKeyboardButton(text="🛒 Магазин", callback_data="shop"),
    ])
    rows.append([
        InlineKeyboardButton(text="⭐ Избранное", callback_data="favorites"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
    ])
    if is_admin:
        rows.append([
            InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
