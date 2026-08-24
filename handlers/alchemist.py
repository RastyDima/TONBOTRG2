import asyncio

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from games.alchemist import INGREDIENTS, INGREDIENT_COUNT, AlchemistGame
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

ALCH_COMMANDS = ("алх", "алхим", "алхимик", "alch", "alchemist")


def is_alch_quick(message: Message) -> bool:
    return quick_command(message.text, ALCH_COMMANDS) is not None


class AlchemistStates(StatesGroup):
    bet = State()


def ingredient_label(idx: int, picked: bool = False) -> str:
    emoji, name = INGREDIENTS[idx]
    return f"✨ {emoji} {name}" if picked else f"{emoji} {name}"


def ingredients_kb(game=None):
    kb = InlineKeyboardBuilder()
    for idx in range(INGREDIENT_COUNT):
        picked = game is not None and idx in game.picks
        kb.button(text=ingredient_label(idx, picked), callback_data=f"alch_pick:{idx}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="alch_cancel"))
    return kb.as_markup()


def pick_text(game, has_bet: bool = False) -> str:
    lines = ["⚗️ <b>Алхимик</b>\n"]
    if has_bet:
        lines.append(f"💳 Ставка: <b>{format_number(game.bet)}</b>\n")
    if game and game.picks:
        lines.append("✨ Выбрано:")
        for idx in game.picks:
            emoji, name = INGREDIENTS[idx]
            lines.append(f"  {emoji} {name}")
        lines.append("\n🪄 Выберите <b>второй</b> ингредиент:")
    else:
        lines.append("🪄 Лаборатория ждёт.\nВыберите <b>первый</b> ингредиент из шести:")
    return "\n".join(lines)


def mixing_phases(game) -> list[str]:
    """Отдельные кадры анимации варки: статус + прогресс-бар + пузырьки."""
    e1, n1 = INGREDIENTS[game.picks[0]]
    e2, n2 = INGREDIENTS[game.picks[1]]
    header = (
        f"⚗️ <b>Алхимик</b>\n\n"
        f"{e1} {n1}\n+\n{e2} {n2}\n\n"
    )
    statuses = [
        ("⚗️ Ингредиенты помещены в котёл...", "🫧"),
        ("🔮 Смесь начинает светиться...", "🫧 ✨"),
        ("✨ Порошок обретает силу...", "✨ 💫"),
        ("💫 Зелье бурлит, цвет меняется...", "💫 💥 ✨"),
        ("⚡ Почти готово...", "⚗️ ✨ 💫"),
    ]
    bars = ["░░░░░░░░░░", "▓░░░░░░░░░", "▓▓░░░░░░░░", "▓▓▓░░░░░░░",
            "▓▓▓▓░░░░░░", "▓▓▓▓▓░░░░░", "▓▓▓▓▓▓░░░░", "▓▓▓▓▓▓▓░░░",
            "▓▓▓▓▓▓▓▓░░", "▓▓▓▓▓▓▓▓▓░", "▓▓▓▓▓▓▓▓▓▓"]
    n = len(statuses)
    frames = []
    for i, (status, bubbles) in enumerate(statuses, 1):
        bar = bars[int((i - 1) / (n - 1) * (len(bars) - 1))]
        frames.append(
            header
            + f"━━━━━━━━━━━━━━\n"
            + f"{status}\n"
            + f"<code>[{bar}]</code> {i * 100 // n}%\n"
            + f"{bubbles}\n"
            + f"━━━━━━━━━━━━━━"
        )
    return frames


def win_text(game) -> str:
    result = game.result
    emoji, name, mult = result
    e1, n1 = INGREDIENTS[game.picks[0]]
    e2, n2 = INGREDIENTS[game.picks[1]]
    return (
        f"⚗️ <b>Алхимик</b>\n\n"
        f"Смешано: {e1} {n1} + {e2} {n2}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"✨ <b>Зелье готово!</b>\n"
        f"{emoji} <b>{name}</b> ×{mult}\n"
        f"💰 Выигрыш: <b>{format_number(game.payout)}</b> "
        f"(+{format_number(game.payout - game.bet)})\n"
        f"━━━━━━━━━━━━━━"
    )


def lose_text(game) -> str:
    result = game.result
    emoji, name, _ = result
    user = db.get_user(game.user_id)
    balance = user["balance"] if user else 0
    return (
        f"⚗️ <b>Алхимик</b>\n\n"
        f"💥 <b>Крак!</b>\n"
        f"{emoji} <b>{name}!</b>\n\n"
        f"Зелье не получилось... Ставка {format_number(game.bet)} сгорела.\n"
        f"💳 Баланс: <b>{format_number(balance)}</b>"
    )


@router.callback_query(F.data == "alchemist", StateFilter("*"))
async def alchemist_menu(callback: CallbackQuery):
    await callback.answer()
    if registry.is_active(callback.from_user.id):
        await callback.answer("Сначала завершите текущую игру!", show_alert=True)
        return
    await callback.message.edit_text(pick_text(None), reply_markup=ingredients_kb())


@router.callback_query(F.data.startswith("alch_pick:"), StateFilter("*"))
async def alchemist_pick(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    idx = int(callback.data.split(":", 1)[1])
    if not 0 <= idx < INGREDIENT_COUNT:
        await callback.answer("Некорректный ингредиент.")
        return

    game = registry.game(user_id)
    if game:
        if game.type != "alchemist":
            await callback.answer("Сначала завершите текущую игру!", show_alert=True)
            return
        if game.ready:
            await callback.answer("Оба ингредиента уже выбраны.")
            return
        if not game.pick(idx):
            await callback.answer("Этот ингредиент уже выбран.", show_alert=True)
            return
        if game.ready:
            await finish_mix(callback, game)
        else:
            await callback.answer("✨ Выбрано!")
            await callback.message.edit_text(pick_text(game), reply_markup=ingredients_kb(game))
        return

    bet = get_pending_bet(user_id)
    if bet is None:
        await state.set_state(AlchemistStates.bet)
        await state.update_data(first_pick=idx)
        await callback.answer()
        await callback.message.edit_text(
            f"⚗️ <b>Алхимик</b> · {INGREDIENTS[idx][0]} {INGREDIENTS[idx][1]}\n\n"
            f"Введите сумму ставки (целое число):",
            reply_markup=cancel_kb(),
        )
        return

    user = db.get_user(user_id)
    if not user or bet > user["balance"]:
        await callback.answer("❌ Недостаточно средств.", show_alert=True)
        await callback.message.edit_text(pick_text(None), reply_markup=ingredients_kb())
        return
    await state.clear()
    db.add_balance(user_id, -bet, "game_bet", "Ставка в игре Алхимик")
    game = AlchemistGame(user_id, bet)
    registry.register(user_id, "alchemist", game)
    game.pick(idx)
    await callback.answer(f"⚗️ Игра началась! Ставка: {format_number(bet)}")
    await callback.message.edit_text(pick_text(game), reply_markup=ingredients_kb(game))


@router.message(F.text, is_alch_quick)
async def quick_alch_start(message: Message, state: FSMContext):
    info = quick_command(message.text, ALCH_COMMANDS)
    bet = info["bet"]
    if registry.is_active(message.from_user.id):
        await message.answer("⚠️ Сначала завершите текущую игру (кнопка «Отмена» или /cancel).")
        return
    if bet is None:
        await state.clear()
        clear_pending_bet(message.from_user.id)
        await message.answer(
            "⚗️ <b>Алхимик</b>\nБыстрый старт: <code>алх 30000</code> — начнёт игру со ставкой.\n\n"
            "Либо выберите первый ингредиент (ставку потом впишете):",
            reply_markup=ingredients_kb(),
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
        f"⚗️ <b>Алхимик</b> · Ставка: <b>{format_number(bet)}</b>\n"
        f"Выберите первый ингредиент — игра начнётся сразу:",
        reply_markup=ingredients_kb(),
    )


@router.message(AlchemistStates.bet)
async def alchemist_process_bet(message: Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return
    data = await state.get_data()
    first_pick = data.get("first_pick")
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
    db.add_balance(message.from_user.id, -bet, "game_bet", "Ставка в игре Алхимик")
    game = AlchemistGame(message.from_user.id, bet)
    registry.register(message.from_user.id, "alchemist", game)
    game.pick(first_pick)
    await state.clear()
    await message.answer(pick_text(game), reply_markup=ingredients_kb(game))


async def finish_mix(callback: CallbackQuery, game) -> None:
    await callback.answer("⚗️ Смешиваю...")
    try:
        frames = mixing_phases(game)
        await callback.message.edit_text(frames[0], reply_markup=None)
        for frame in frames[1:]:
            await asyncio.sleep(1.1)
            await callback.message.edit_text(frame)
        await asyncio.sleep(1.3)
    except Exception:
        # Сообщение могли удалить во время анимации — не роняем хендлер.
        pass

    game.resolve()
    if game.multiplier <= 0:
        lose_game(game.user_id)
        final_text = lose_text(game)
    else:
        cashout_game(game.user_id)
        final_text = win_text(game)

    try:
        await callback.message.edit_text(final_text)
    except Exception:
        try:
            await callback.bot.send_message(callback.message.chat.id, final_text)
        except Exception:
            pass


@router.callback_query(F.data == "alch_cancel", StateFilter("*"))
async def alchemist_cancel(callback: CallbackQuery):
    cancel_game(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text("❌ Игра отменена. Ставка возвращена на баланс.")
