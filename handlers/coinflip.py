from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MAX_BET
from database import db
from games.coinflip import CoinFlipGame, PAYOUT_MULTIPLIER
from keyboards.common import back_button, cancel_kb
from utils.game_registry import GAME_XP_PLAY, GAME_XP_WIN, award_progress, progress_text, registry
from utils.helpers import format_number, parse_bet, quick_command

router = Router()

CF_COMMANDS = ("мон", "монетка", "ор", "орёл", "coin", "coinflip")


def is_cf_quick(message: Message) -> bool:
    return quick_command(message.text, CF_COMMANDS) is not None


class CoinFlipStates(StatesGroup):
    bet = State()


def choice_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🪙 Орёл (×{PAYOUT_MULTIPLIER})", callback_data="cf_pick:орёл")
    kb.button(text=f"🪙 Решка (×{PAYOUT_MULTIPLIER})", callback_data="cf_pick:решка")
    kb.adjust(2)
    kb.row(back_button("menu_games"))
    return kb.as_markup()


def result_text(game: CoinFlipGame, user_balance: int) -> str:
    coin = "🪙" if game.result == "орёл" else "🪙"
    if game.won:
        return (
            f"🪙 <b>Монетка</b>\n\n"
            f"Выпало: <b>{game.result.upper()}</b> {coin}\n\n"
            f"🎉 <b>Победа!</b>\n"
            f"Множитель: ×{PAYOUT_MULTIPLIER}\n"
            f"Выигрыш: <b>{format_number(game.payout)}</b> TON "
            f"(+{format_number(game.payout - game.bet)})\n\n"
            f"💳 Баланс: {format_number(user_balance)}"
        )
    return (
        f"🪙 <b>Монетка</b>\n\n"
        f"Выпало: <b>{game.result.upper()}</b> {coin}\n\n"
        f"💀 <b>Проигрыш!</b>\n"
        f"Ставка {format_number(game.bet)} TON сгорела.\n\n"
        f"💳 Баланс: {format_number(user_balance)}"
    )


@router.callback_query(F.data == "coinflip", StateFilter("*"))
async def coinflip_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if registry.is_active(callback.from_user.id):
        await callback.answer("Сначала завершите текущую игру!", show_alert=True)
        return
    await state.set_state(CoinFlipStates.bet)
    await callback.answer()
    await callback.message.edit_text(
        f"🪙 <b>Монетка</b>\n\n"
        f"Выберите сторону:\n"
        f"🪙 <b>Орёл</b> — ×{PAYOUT_MULTIPLIER}\n"
        f"🪙 <b>Решка</b> — ×{PAYOUT_MULTIPLIER}\n\n"
        f"Введите ставку от 1 до {format_number(MAX_BET)} TON:",
        reply_markup=cancel_kb(),
    )


@router.message(F.text, is_cf_quick)
async def quick_cf_start(message: Message, state: FSMContext):
    info = quick_command(message.text, CF_COMMANDS)
    bet = info["bet"]
    if registry.is_active(message.from_user.id):
        await message.answer("⚠️ Сначала завершите текущую игру.")
        return
    if bet is None:
        await state.clear()
        await message.answer(
            "🪙 <b>Монетка</b>\nБыстрый старт: <code>мон 30000</code> — начнёт игру со ставкой.\n\n"
            "Либо выберите сторону (ставку потом впишете):",
            reply_markup=choice_kb(),
        )
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    if bet > user["balance"]:
        await message.answer(f"❌ Недостаточно средств. Баланс: {format_number(user['balance'])}")
        return
    await state.clear()
    game = CoinFlipGame(message.from_user.id, bet)
    db.add_balance(message.from_user.id, -bet, "game_bet", "Ставка в Монетке")
    registry.register(message.from_user.id, "coinflip", game)
    await message.answer(
        f"🪙 <b>Монетка</b> · Ставка: <b>{format_number(bet)}</b> TON\n"
        f"Выберите сторону:",
        reply_markup=choice_kb(),
    )


@router.message(CoinFlipStates.bet)
async def coinflip_process_bet(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return
    bet = parse_bet(message.text)
    if bet is None:
        await message.answer(f"❌ Введите ставку от 1 до {format_number(MAX_BET)} TON:")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    if registry.is_active(message.from_user.id):
        await message.answer("⚠️ Сначала завершите текущую игру.")
        return
    if bet > user["balance"]:
        await message.answer(f"❌ Недостаточно средств. Баланс: {format_number(user['balance'])}")
        return
    db.add_balance(message.from_user.id, -bet, "game_bet", "Ставка в Монетке")
    game = CoinFlipGame(message.from_user.id, bet)
    registry.register(message.from_user.id, "coinflip", game)
    await state.clear()
    await message.answer(
        f"🪙 <b>Монетка</b> · Ставка: <b>{format_number(bet)}</b> TON\n"
        f"Выберите сторону:",
        reply_markup=choice_kb(),
    )


@router.callback_query(F.data.startswith("cf_pick:"), StateFilter("*"))
async def coinflip_pick(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    game = registry.game(user_id)
    if not game or game.type != "coinflip":
        await callback.answer("Игра не найдена. Начните новую.", show_alert=True)
        return
    if game.is_over:
        await callback.answer("Игра уже завершена.")
        return

    choice = callback.data.split(":", 1)[1]
    game.flip(choice)

    if game.won:
        db.add_balance(user_id, game.payout, "game_win", "Выигрыш в Монетке")

    user = db.get_user(user_id)
    balance = user["balance"] if user else 0

    registry.release(user_id)
    db.add_game(user_id, "coinflip", game.bet, game.payout, "win" if game.won else "lose")
    db.update_stats(user_id, "win" if game.won else "lose", game.bet, game.payout)
    level_msg = progress_text(award_progress(user_id, GAME_XP_PLAY + (GAME_XP_WIN if game.won else 0)))

    await callback.answer("🎉" if game.won else "💀")
    await callback.message.edit_text(result_text(game, balance) + level_msg, reply_markup=None)
