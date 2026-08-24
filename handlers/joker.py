from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from games.joker import BUTTONS, JokerGame, get_joker_levels
from keyboards.common import back_button, cancel_kb
from utils.game_registry import (
    cancel_game,
    cashout_game,
    clear_pending_bet,
    get_pending_bet,
    lose_game,
    registry,
    set_pending_bet,
)
from utils.helpers import format_number, parse_bet, quick_command

router = Router()

JOKER_COMMANDS = ("дж", "ж", "жокер", "joker")


def is_joker_quick(message: Message) -> bool:
    return quick_command(message.text, JOKER_COMMANDS) is not None


class JokerStates(StatesGroup):
    bet = State()


def levels_kb():
    kb = InlineKeyboardBuilder()
    levels = get_joker_levels()
    for lvl in range(1, 3):
        cfg = levels[lvl]
        kb.button(
            text=f"{lvl} · 💀 {cfg['skulls']} · ×{cfg['mult']} за дверь",
            callback_data=f"joker:{lvl}",
        )
    kb.adjust(1)
    kb.row(back_button("menu_games"))
    return kb.as_markup()


def field_text(game) -> str:
    text = (
        f"🃏 <b>Джокер</b> · Уровень {game.level} · 💀 {game.skulls} · ×{game.round_multiplier} за дверь\n"
        f"Раунд: {game.round} · Ставка: {format_number(game.bet)}\n"
    )
    for i, rd in enumerate(game.rounds, 1):
        text += f"\n🏁 Раунд {i}:\n{game.reveal_line(rd)}\n"
    text += (
        f"\n➡️ Раунд {game.round}:\n{game.hidden_line()}\n\n"
        f"В трёх дверях спрятано 💀 <b>{game.skulls}</b> скелета(ов).\n\n"
        f"💰 Множитель: <b>{game.multiplier}x</b>\n"
        f"Выигрыш: <b>{format_number(game.payout)}</b>"
    )
    return text


def field_kb(game):
    kb = InlineKeyboardBuilder()
    for i in range(BUTTONS):
        kb.button(text=f"🚪 {i + 1}", callback_data=f"joker_pick:{i}")
    kb.adjust(BUTTONS)
    kb.row(
        InlineKeyboardButton(
            text=f"💰 Забрать {format_number(game.payout)}", callback_data="joker_cashout"
        )
    )
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="joker_cancel"))
    return kb.as_markup()


def win_text(game) -> str:
    text = "🎉 <b>Победа!</b>\n"
    for i, rd in enumerate(game.rounds, 1):
        text += f"\n🏁 Раунд {i}:\n{game.reveal_line(rd)}\n"
    text += (
        f"\nПройдено раундов: {game.round - 1}\n"
        f"💰 Выигрыш: <b>{format_number(game.payout)}</b> "
        f"(+{format_number(game.payout - game.bet)})"
    )
    return text


def lose_text(game) -> str:
    user = db.get_user(game.user_id)
    balance = user["balance"] if user else 0
    text = "💀 <b>Вы открыли дверь со скелетом!</b>\n"
    for i, rd in enumerate(game.rounds, 1):
        text += f"\n🏁 Раунд {i}:\n{game.reveal_line(rd)}\n"
    text += (
        f"\nПройдено раундов: {game.round - 1}\n"
        f"Ставка {format_number(game.bet)} сгорела.\n"
        f"💳 Баланс: <b>{format_number(balance)}</b>"
    )
    return text


@router.callback_query(F.data == "joker", StateFilter("*"))
async def joker_level_menu(callback: CallbackQuery):
    await callback.answer()
    if registry.is_active(callback.from_user.id):
        await callback.answer("Сначала завершите текущую игру!", show_alert=True)
        return
    await callback.message.edit_text(
        "🃏 <b>Джокер</b>\nВыберите уровень риска:\n"
        "💀 1 — низкий риск, множитель ×1.6\n"
        "💀 2 — высокий риск, множитель ×3.5",
        reply_markup=levels_kb(),
    )


@router.callback_query(F.data.startswith("joker:"), StateFilter("*"))
async def joker_choose_level(callback: CallbackQuery, state: FSMContext):
    level = int(callback.data.split(":", 1)[1])
    cfg = get_joker_levels()[level]
    bet = get_pending_bet(callback.from_user.id)
    if bet is not None:
        await state.clear()
        if registry.is_active(callback.from_user.id):
            await callback.answer(
                "⚠️ Сначала завершите текущую игру!", show_alert=True
            )
            return
        user = db.get_user(callback.from_user.id)
        if not user or bet > user["balance"]:
            await callback.answer("❌ Недостаточно средств.", show_alert=True)
            await callback.message.edit_text(
                "🃏 <b>Джокер</b>\nВыберите уровень риска:\n"
                "💀 1 — низкий риск, множитель ×1.6\n"
                "💀 2 — высокий риск, множитель ×3.5",
                reply_markup=levels_kb(),
            )
            return
        db.add_balance(callback.from_user.id, -bet, "game_bet", "Ставка в игре Джокер")
        game = JokerGame(callback.from_user.id, bet, level)
        registry.register(callback.from_user.id, "joker", game)
        await callback.answer(f"🃏 Игра началась! Ставка: {format_number(bet)}")
        await callback.message.edit_text(field_text(game), reply_markup=field_kb(game))
        return
    await state.set_state(JokerStates.bet)
    await state.update_data(level=level)
    await callback.answer()
    await callback.message.edit_text(
        f"🃏 <b>Джокер</b> · Уровень {level} · 💀 {cfg['skulls']} · ×{cfg['mult']} за дверь\n\n"
        f"Введите сумму ставки (целое число):",
        reply_markup=cancel_kb(),
    )


@router.message(F.text, is_joker_quick)
async def quick_joker_start(message: Message, state: FSMContext):
    info = quick_command(message.text, JOKER_COMMANDS)
    bet = info["bet"]
    if registry.is_active(message.from_user.id):
        await message.answer("⚠️ Сначала завершите текущую игру (кнопка «Отмена» или /cancel).")
        return
    if bet is None:
        await state.clear()
        clear_pending_bet(message.from_user.id)
        await message.answer(
            "🃏 <b>Джокер</b>\nБыстрый старт: <code>дж 30000</code> — начнёт игру со ставкой.\n\n"
            "Либо выберите уровень риска (ставку потом впишете):",
            reply_markup=levels_kb(),
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
    set_pending_bet(message.from_user.id, bet)
    await message.answer(
        f"🃏 <b>Джокер</b> · Ставка: <b>{format_number(bet)}</b>\n"
        f"Выберите уровень риска — игра начнётся сразу:",
        reply_markup=levels_kb(),
    )


@router.message(JokerStates.bet)
async def joker_process_bet(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return
    data = await state.get_data()
    level = data.get("level")
    bet = parse_bet(message.text)
    if bet is None:
        await message.answer("❌ Некорректная сумма. Введите целое число от 1:")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    if registry.is_active(message.from_user.id):
        await message.answer("⚠️ Сначала завершите текущую игру (кнопка «Отмена» или /cancel).")
        return
    if bet > user["balance"]:
        await message.answer(f"❌ Недостаточно средств. Баланс: {format_number(user['balance'])}")
        return
    db.add_balance(message.from_user.id, -bet, "game_bet", "Ставка в игре Джокер")
    game = JokerGame(message.from_user.id, bet, level)
    registry.register(message.from_user.id, "joker", game)
    await state.clear()
    await message.answer(field_text(game), reply_markup=field_kb(game))


@router.callback_query(F.data.startswith("joker_pick:"), StateFilter("*"))
async def joker_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = registry.game(user_id)
    if not game or game.type != "joker":
        await callback.answer("Игра не найдена. Начните новую.", show_alert=True)
        return
    if game.is_over:
        await callback.answer("Игра уже завершена.")
        return
    pos = int(callback.data.split(":", 1)[1])
    if pos < 0 or pos >= BUTTONS:
        await callback.answer("Некорректная дверь.")
        return
    if game.pick(pos) == "skull":
        lose_game(user_id)
        await callback.answer("💀 Скелет!")
        await callback.message.edit_text(lose_text(game), reply_markup=None)
        return
    await callback.answer(f"Множитель: {game.multiplier}x")
    await callback.message.edit_text(field_text(game), reply_markup=field_kb(game))


@router.callback_query(F.data == "joker_cashout", StateFilter("*"))
async def joker_cashout(callback: CallbackQuery):
    result = cashout_game(callback.from_user.id)
    if not result:
        await callback.answer("Игра не найдена. Начните новую.", show_alert=True)
        return
    game, payout = result
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"💰 <b>Выигрыш: {format_number(payout)}</b> "
        f"(+{format_number(payout - game.bet)})\n"
        f"Множитель: {game.multiplier}x",
    )


@router.callback_query(F.data == "joker_cancel", StateFilter("*"))
async def joker_cancel(callback: CallbackQuery):
    cancel_game(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text("❌ Игра отменена. Ставка возвращена на баланс.")