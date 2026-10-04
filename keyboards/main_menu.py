from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(is_admin: bool = False):
    rows = []
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
    if is_admin:
        rows.append([
            InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
