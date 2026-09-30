from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from keyboards.games import games_menu, ton_games, rubies_games
from utils.game_registry import clear_pending_bet

router = Router()


@router.callback_query(F.data == "noop", StateFilter("*"))
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "menu_games", StateFilter("*"))
async def games_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    clear_pending_bet(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        "🎮 <b>Игры</b>\n\nВыберите валюту:",
        reply_markup=games_menu(),
    )


@router.callback_query(F.data == "games_ton", StateFilter("*"))
async def ton_games_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    clear_pending_bet(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        "🎲 <b>Игры на TON</b>\n\n"
        "💣 <b>Мины</b> — поле 5×5, от 1 до 10 мин\n"
        "🃏 <b>Джокер</b> — карточная игра с уровнями риска\n"
        "⚗️ <b>Алхимик</b> — смешай 2 ингредиента и получи зелье\n"
        "🂡 <b>21</b> — набери больше дилера, не превысив 21",
        reply_markup=ton_games(),
    )


@router.callback_query(F.data == "games_rubies", StateFilter("*"))
async def rubies_games_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    clear_pending_bet(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        "💎 <b>Игры на Рубины</b>\n\n"
        "🎰 <b>Рулетка</b> — красный/чёрный/рубин",
        reply_markup=rubies_games(),
    )
