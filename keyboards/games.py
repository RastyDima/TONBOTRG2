from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from keyboards.common import back_button


def games_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎲 ТОН", callback_data="games_ton"),
            InlineKeyboardButton(text="💎 РУБИНЫ", callback_data="games_rubies"),
        ],
        [back_button("menu")],
    ])


def ton_games():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💣 Мины", callback_data="mines"),
            InlineKeyboardButton(text="🃏 Джокер", callback_data="joker"),
        ],
        [
            InlineKeyboardButton(text="⚗️ Алхимик", callback_data="alchemist"),
            InlineKeyboardButton(text="🪙 Монетка", callback_data="coinflip"),
        ],
        [InlineKeyboardButton(text="🂡 21", callback_data="blackjack")],
        [back_button("menu_games")],
    ])


def rubies_games():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Рулетка", callback_data="ruby_roulette")],
        [back_button("menu_games")],
    ])
