from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MAX_BET
from database import db
from games.blackjack import BlackjackGame, PAYOUT_MULTIPLIER
from keyboards.common import cancel_kb
from utils.game_registry import (
    cashout_game,
    draw_game,
    lose_game,
    progress_text,
    registry,
)
from utils.helpers import format_number, parse_bet, quick_command

router = Router()
BLACKJACK_COMMANDS = ("21", "двадцатьодин", "блэкджек", "blackjack")


class BlackjackStates(StatesGroup):
    bet = State()


def is_blackjack_quick(message: Message) -> bool:
    return quick_command(message.text, BLACKJACK_COMMANDS) is not None


def cards_text(cards) -> str:
    return "  ".join(f"{rank}{suit}" for rank, suit in cards)


def round_text(game: BlackjackGame) -> str:
    return (
        f"🂡 <b>21</b> · Ставка: <b>{format_number(game.bet)}</b> TON\n\n"
        f"🎩 Дилер: {cards_text(game.dealer[:1])}  🂠\n"
        f"🫵 Вы: {cards_text(game.player)}  ·  <b>{game.player_total}</b> очков\n\n"
        "Возьмите карту или остановитесь. Дилер добирает до 17.\n"
        f"Победа: ×{PAYOUT_MULTIPLIER} · Ничья: возврат ставки.\n"
        "Сдаться или выйти после раздачи — ставка проиграна."
    )


def round_kb(game: BlackjackGame):
    kb = InlineKeyboardBuilder()
    if game.can_hit:
        kb.button(text="🃏 Взять карту", callback_data=f"bj:hit:{game.turn}")
    kb.button(text="✋ Остановиться", callback_data=f"bj:stand:{game.turn}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(
        text="❌ Сдаться · ставка сгорит",
        callback_data=f"bj:forfeit:{game.turn}",
    ))
    return kb.as_markup()


def result_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🂡 Ещё раз", callback_data="blackjack")
    kb.button(text="🎮 К играм", callback_data="games_ton")
    kb.adjust(2)
    return kb.as_markup()


def result_text(game: BlackjackGame, balance: int) -> str:
    result = {
        "win": f"🎉 <b>Победа!</b> Выигрыш: {format_number(game.payout)} TON "
               f"(+{format_number(game.payout - game.bet)}).",
        "lose": f"💀 <b>Поражение.</b> Ставка {format_number(game.bet)} TON проиграна.",
        "draw": "🤝 <b>Ничья.</b> Ставка возвращена.",
    }[game.outcome]
    return (
        f"🂡 <b>21 · Итог раздачи</b>\n\n"
        f"🎩 Дилер: {cards_text(game.dealer)}  ·  <b>{game.dealer_total}</b>\n"
        f"🫵 Вы: {cards_text(game.player)}  ·  <b>{game.player_total}</b>\n\n"
        f"{result}\n"
        f"💳 Баланс: <b>{format_number(balance)}</b> TON"
    )


async def prompt_bet(message: Message, state: FSMContext, user_id: int | None = None,
                     edit: bool = False) -> None:
    user_id = user_id if user_id is not None else message.from_user.id
    if registry.is_active(user_id):
        await message.answer("⚠️ Сначала завершите текущую игру.")
        return
    await state.set_state(BlackjackStates.bet)
    send = message.edit_text if edit else message.answer
    await send(
        "🂡 <b>21</b>\n\n"
        "Соберите больше очков, чем дилер, но не выше 21. "
        f"Победа — ×{PAYOUT_MULTIPLIER}; ничья — возврат ставки.\n"
        "После раздачи отмена считается поражением.\n\n"
        f"Введите ставку от 1 до {format_number(MAX_BET)} TON:",
        reply_markup=cancel_kb(),
    )


async def start_round(message: Message, state: FSMContext, bet: int) -> None:
    user_id = message.from_user.id
    if registry.is_active(user_id):
        await message.answer("⚠️ Сначала завершите текущую игру.")
        return
    user = db.get_user(user_id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    if bet > user["balance"]:
        await message.answer(f"❌ Недостаточно средств. Баланс: {format_number(user['balance'])}")
        return
    game = BlackjackGame(user_id, bet)
    if not registry.register(user_id, "blackjack", game):
        await message.answer("⚠️ Сначала завершите текущую игру.")
        return
    try:
        db.add_balance(user_id, -bet, "game_bet", "Ставка в игре 21")
    except Exception:
        registry.release(user_id)
        raise
    await state.clear()
    await message.answer(round_text(game), reply_markup=round_kb(game))


@router.callback_query(F.data == "blackjack", StateFilter("*"))
async def blackjack_menu(callback: CallbackQuery, state: FSMContext):
    if registry.is_active(callback.from_user.id):
        await callback.answer("Сначала завершите текущую игру!", show_alert=True)
        return
    await callback.answer()
    await prompt_bet(callback.message, state, callback.from_user.id, edit=True)


@router.message(Command("blackjack"))
async def blackjack_command(message: Message, state: FSMContext):
    await prompt_bet(message, state)


@router.message(F.text, is_blackjack_quick)
async def blackjack_quick(message: Message, state: FSMContext):
    info = quick_command(message.text, BLACKJACK_COMMANDS)
    if info["bet"] is None:
        await prompt_bet(message, state)
    else:
        await start_round(message, state, info["bet"])


@router.message(BlackjackStates.bet)
async def blackjack_bet(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return
    bet = parse_bet(message.text)
    if bet is None:
        await message.answer(f"❌ Введите ставку от 1 до {format_number(MAX_BET)} TON:")
        return
    await start_round(message, state, bet)


@router.callback_query(F.data.startswith("bj:"), StateFilter("*"))
async def blackjack_action(callback: CallbackQuery):
    game = registry.game(callback.from_user.id)
    if not game or game.type != "blackjack" or game.outcome is not None:
        await callback.answer("Раздача уже завершена.", show_alert=True)
        return
    try:
        _, action, turn_text = callback.data.split(":")
        turn = int(turn_text)
    except (ValueError, TypeError):
        await callback.answer("Некорректный ход.", show_alert=True)
        return
    if turn != game.turn or action not in {"hit", "stand", "forfeit"}:
        await callback.answer("Этот ход уже сделан.", show_alert=True)
        return
    moved = {"hit": game.hit, "stand": game.stand, "forfeit": game.forfeit}[action]()
    if not moved:
        await callback.answer("Этот ход недоступен.", show_alert=True)
        return
    if game.outcome is None:
        await callback.answer("Карта открыта.")
        await callback.message.edit_text(round_text(game), reply_markup=round_kb(game))
        return

    user_id = callback.from_user.id
    if game.outcome == "win":
        settled = cashout_game(user_id)
        progress = progress_text(settled[2]) if settled else ""
    elif game.outcome == "draw":
        draw_game(user_id)
        progress = ""
    else:
        settled = lose_game(user_id)
        progress = progress_text(settled[1]) if settled else ""
    user = db.get_user(user_id)
    balance = user["balance"] if user else 0
    await callback.answer()
    await callback.message.edit_text(
        result_text(game, balance) + progress,
        reply_markup=result_kb(),
    )
