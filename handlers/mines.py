from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MAX_BET, MAX_GAME_MULTIPLIER
from database import db
from games.mines import COLS, FIELD_SIZE, MAX_MINES, MIN_MINES, MinesGame, ROWS
from keyboards.common import back_button, cancel_kb
from utils.game_registry import (
    cancel_game,
    cashout_game,
    clear_pending_bet,
    get_pending_bet,
    lose_game,
    progress_text,
    registry,
    set_pending_bet,
)
from utils.helpers import format_number, parse_bet, quick_command

router = Router()

MINES_COMMANDS = ("м", "мин", "мины", "mines")


def is_mines_quick(message: Message) -> bool:
    return quick_command(message.text, MINES_COMMANDS) is not None


class MinesStates(StatesGroup):
    bet = State()


def place_mines_bet(user_id: int, bet: int, count: int) -> MinesGame | None:
    game = MinesGame(user_id, bet, count)
    if not registry.register(user_id, "mines", game):
        return None
    try:
        spent = db.start_mines_round(game)
    except Exception:
        registry.release(user_id)
        raise
    if not spent:
        registry.release(user_id)
        return None
    game.persisted = True
    return game


def mines_count_kb():
    kb = InlineKeyboardBuilder()
    for n in range(1, 11):
        kb.button(text=str(n), callback_data=f"mines:{n}")
    kb.adjust(5, 5)
    kb.row(back_button("menu_games"))
    return kb.as_markup()


def render_field(game) -> str:
    lines = []
    for r in range(ROWS):
        line = ""
        for c in range(COLS):
            idx = r * COLS + c
            if idx in game.mine_positions:
                line += "💣"
            elif idx in game.revealed:
                line += "🟩"
            else:
                line += "⬛"
        lines.append(line)
    return "\n".join(lines)


def field_text(game) -> str:
    text = (
        f"💣 <b>Мины</b> · 5×5\n"
        f"Мин: {game.mines} · Открыто: {game.safe_revealed}/{game.safe_total}\n"
        f"Ставка: {format_number(game.bet)}\n\n"
        f"💰 Множитель: <b>{game.multiplier}x</b>\n"
        f"Потенциальный выигрыш: <b>{format_number(game.payout)}</b>"
    )
    if not game.can_cashout:
        text += "\nОткройте безопасные клетки, чтобы забрать выигрыш."
    elif game.safe_revealed:
        text += "\nПосле открытия клетки отмена считается поражением."
    return text


def field_kb(game):
    kb = InlineKeyboardBuilder()
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            idx = r * COLS + c
            text = "🟩" if idx in game.revealed else "⬛"
            row.append(InlineKeyboardButton(text=text, callback_data=f"mines_cell:{game.public_id}:{idx}"))
        kb.row(*row)
    if game.can_cashout:
        kb.row(InlineKeyboardButton(
            text=f"💰 Забрать {format_number(game.payout)}", callback_data=f"mines_cashout:{game.public_id}"
        ))
    kb.row(InlineKeyboardButton(
        text="❌ Отмена" if game.can_refund else "❌ Сдаться · ставка сгорит",
        callback_data=f"mines_cancel:{game.public_id}",
    ))
    return kb.as_markup()


def win_text(game) -> str:
    return (
        f"🎉 <b>Победа!</b>\n\n{render_field(game)}\n\n"
        f"Множитель: {game.multiplier}x\n"
        f"💰 Выигрыш: <b>{format_number(game.payout)}</b> "
        f"(+{format_number(game.payout - game.bet)})\n"
        f"🍀<i>seed</i>: <code>{game.seed}</code>"
    )


def lose_text(game) -> str:
    user = db.get_user(game.user_id)
    balance = user["balance"] if user else 0
    return (
        f"💥 <b>Вы наступили на мину!</b>\n\n{render_field(game)}\n\n"
        f"Ставка {format_number(game.bet)} сгорела.\n"
        f"💳 Баланс: <b>{format_number(balance)}</b>\n"
        f"🍀<i>seed</i>: <code>{game.seed}</code>"
    )


@router.callback_query(F.data == "mines", StateFilter("*"))
async def mines_count_menu(callback: CallbackQuery):
    await callback.answer()
    active = registry.get(callback.from_user.id)
    if active and active["type"] == "mines":
        game = active["game"]
        await callback.message.edit_text(field_text(game), reply_markup=field_kb(game))
        return
    if active:
        await callback.answer("Сначала завершите текущую игру!", show_alert=True)
        return
    await callback.message.edit_text(
        "💣 <b>Мины</b>\nВыберите количество мин (1–10):", reply_markup=mines_count_kb()
    )


@router.callback_query(F.data.startswith("mines:"), StateFilter("*"))
async def mines_choose_count(callback: CallbackQuery, state: FSMContext):
    try:
        count = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        count = 0
    if not MIN_MINES <= count <= MAX_MINES:
        await callback.answer("Некорректное количество мин.", show_alert=True)
        return
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
                "💣 <b>Мины</b>\nВыберите количество мин (1–10):", reply_markup=mines_count_kb()
            )
            return
        game = place_mines_bet(callback.from_user.id, bet, count)
        if game is None:
            await callback.answer("❌ Ставка недоступна или уже идёт другая игра.", show_alert=True)
            return
        await callback.answer(f"💣 Игра началась! Ставка: {format_number(bet)}")
        await callback.message.edit_text(field_text(game), reply_markup=field_kb(game))
        return
    await state.set_state(MinesStates.bet)
    await state.update_data(mines=count)
    await callback.answer()
    await callback.message.edit_text(
        f"💣 <b>Мины</b> · Мин: {count}\n\nВведите ставку от 1 до {format_number(MAX_BET)}:",
        reply_markup=cancel_kb(),
    )


@router.message(F.text, is_mines_quick)
async def quick_mines_start(message: Message, state: FSMContext):
    info = quick_command(message.text, MINES_COMMANDS)
    bet = info["bet"]
    if registry.is_active(message.from_user.id):
        await message.answer("⚠️ Сначала завершите текущую игру (кнопка «Отмена» или /cancel).")
        return
    if bet is None:
        # «м» без суммы — молча игнорируем, чтобы не спамить лишними сообщениями.
        await state.clear()
        clear_pending_bet(message.from_user.id)
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
        f"💣 <b>Мины</b> · Ставка: <b>{format_number(bet)}</b>\n"
        f"Выберите количество мин (1–10) — игра начнётся сразу:",
        reply_markup=mines_count_kb(),
    )


@router.message(MinesStates.bet)
async def mines_process_bet(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return
    data = await state.get_data()
    mines = data.get("mines")
    if type(mines) is not int or not MIN_MINES <= mines <= MAX_MINES:
        await state.clear()
        await message.answer("❌ Выберите количество мин заново.")
        return
    bet = parse_bet(message.text)
    if bet is None:
        await message.answer(f"❌ Введите ставку от 1 до {format_number(MAX_BET)}:")
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
    game = place_mines_bet(message.from_user.id, bet, mines)
    if game is None:
        await message.answer("❌ Ставка недоступна или уже идёт другая игра.")
        return
    await state.clear()
    await message.answer(field_text(game), reply_markup=field_kb(game))


@router.callback_query(F.data.startswith("mines_cell:"), StateFilter("*"))
async def mines_reveal(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = registry.game(user_id)
    if not game or game.type != "mines":
        await callback.answer("Игра не найдена. Начните новую.", show_alert=True)
        return
    if game.is_over:
        await callback.answer("Игра уже завершена.")
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[1] != game.public_id:
        await callback.answer("Кнопка от старого раунда.", show_alert=True)
        return
    try:
        idx = int(parts[2])
    except ValueError:
        idx = -1
    if not 0 <= idx < FIELD_SIZE:
        await callback.answer("Некорректная клетка.", show_alert=True)
        return
    if idx in game.revealed:
        await callback.answer("Клетка уже открыта.")
        return
    if idx in game.mine_positions:
        result = lose_game(user_id)
        await callback.answer("💥 Бум!")
        level_msg = progress_text(result[1]) if result else ""
        await callback.message.edit_text(lose_text(game) + level_msg, reply_markup=None)
        return
    game.revealed.add(idx)
    if not db.save_mines_round(game):
        registry.release(user_id)
        await callback.answer("Раунд изменился. Откройте игру снова.", show_alert=True)
        return
    if game.safe_revealed == game.safe_total or game.multiplier >= MAX_GAME_MULTIPLIER:
        maxed = game.safe_revealed < game.safe_total
        result = cashout_game(user_id)
        if result:
            game, payout, progress = result
            level_msg = progress_text(progress)
            await callback.answer()
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                f"🎉 <b>{'Достигнут максимальный множитель!' if maxed else 'Всё поле безопасно!'}</b>\n"
                f"💰 Выигрыш: <b>{format_number(payout)}</b> "
                f"(+{format_number(payout - game.bet)})\n"
                f"Множитель: {game.multiplier}x"
                f"{level_msg}",
            )
        return
    await callback.answer(f"Множитель: {game.multiplier}x")
    await callback.message.edit_text(field_text(game), reply_markup=field_kb(game))


@router.callback_query(F.data.startswith("mines_cashout"), StateFilter("*"))
async def mines_cashout(callback: CallbackQuery):
    active = registry.game(callback.from_user.id)
    if not active or active.type != "mines" or callback.data != f"mines_cashout:{active.public_id}":
        await callback.answer("Кнопка от старого раунда.", show_alert=True)
        return
    result = cashout_game(callback.from_user.id)
    if not result:
        await callback.answer("Сначала откройте безопасные клетки или начните новую игру.", show_alert=True)
        return
    game, payout, progress = result
    level_msg = progress_text(progress)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"💰 <b>Выигрыш: {format_number(payout)}</b> "
        f"(+{format_number(payout - game.bet)})\n"
        f"Множитель: {game.multiplier}x"
        f"{level_msg}",
    )


@router.callback_query(F.data.startswith("mines_cancel"), StateFilter("*"))
async def mines_cancel(callback: CallbackQuery):
    active = registry.game(callback.from_user.id)
    if not active or active.type != "mines" or callback.data != f"mines_cancel:{active.public_id}":
        await callback.answer("Кнопка от старого раунда.", show_alert=True)
        return
    game = cancel_game(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        "❌ Игра отменена. Ставка возвращена на баланс."
        if game else "❌ Игра завершена. Ставка проиграна."
    )
