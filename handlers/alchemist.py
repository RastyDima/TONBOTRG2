import asyncio

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MAX_BET
from database import db
from games.alchemist import BREW_MODES, INGREDIENTS, INGREDIENT_COUNT, AlchemistGame
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
        lines.append(
            "🪄 Выберите два ингредиента, затем способ варки. Шансы и выплата будут показаны до запуска.\n"
            "Выберите <b>первый</b> ингредиент из шести:"
        )
    return "\n".join(lines)


def brew_text(game) -> str:
    emoji, name, _ = game.recipe
    first = INGREDIENTS[game.picks[0]]
    second = INGREDIENTS[game.picks[1]]
    lines = [
        "⚗️ <b>Алхимик · выбор варки</b>",
        f"{first[0]} {first[1]} + {second[0]} {second[1]}",
        f"{emoji} <b>{name}</b> · ставка {format_number(game.bet)}",
        "",
    ]
    for mode, option in game.brew_options.items():
        icon = "🛡" if mode == "steady" else "🔥"
        lines.append(
            f"{icon} <b>{BREW_MODES[mode]}</b>: шанс {option['threshold'] / 100:.1f}% "
            f"· ×{option['multiplier']} · выигрыш {format_number(option['payout'])}"
        )
    lines.append("\nВыберите способ варки. После выбора ставка будет разыграна.")
    return "\n".join(lines)


def brew_kb():
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🛡 Стабилизировать", callback_data="alch_brew:steady"),
        InlineKeyboardButton(text="🔥 Усилить", callback_data="alch_brew:wild"),
    )
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="alch_cancel"))
    return kb.as_markup()


def mixing_phases(game) -> list[str]:
    """Отдельные кадры анимации варки: статус + прогресс-бар + пузырьки."""
    e1, n1 = INGREDIENTS[game.picks[0]]
    e2, n2 = INGREDIENTS[game.picks[1]]
    header = (
        f"⚗️ <b>Алхимик</b>\n\n"
        f"{e1} {n1}\n+\n{e2} {n2}\n"
        f"{BREW_MODES[game.mode]} · шанс {game.chance_threshold / 100:.1f}%\n\n"
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
    emoji, name, _ = result
    e1, n1 = INGREDIENTS[game.picks[0]]
    e2, n2 = INGREDIENTS[game.picks[1]]
    return (
        f"⚗️ <b>Алхимик</b>\n\n"
        f"Смешано: {e1} {n1} + {e2} {n2}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"✨ <b>Зелье готово!</b>\n"
        f"{emoji} <b>{name}</b> · {BREW_MODES[game.mode]} ×{game.multiplier}\n"
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
        f"{emoji} <b>{name}</b> · {BREW_MODES[game.mode]}\n\n"
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
    try:
        idx = int(callback.data.split(":", 1)[1])
    except (ValueError, TypeError):
        await callback.answer("Некорректный ингредиент.", show_alert=True)
        return
    if not 0 <= idx < INGREDIENT_COUNT:
        await callback.answer("Некорректный ингредиент.")
        return

    game = registry.game(user_id)
    if game:
        if game.type != "alchemist":
            await callback.answer("Сначала завершите текущую игру!", show_alert=True)
            return
        if game.ready:
            await callback.answer("Выберите способ варки.")
            return
        if not game.pick(idx):
            await callback.answer("Этот ингредиент уже выбран.", show_alert=True)
            return
        if game.ready:
            await callback.answer("Выберите способ варки.")
            await callback.message.edit_text(brew_text(game), reply_markup=brew_kb())
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
            f"Введите ставку от 1 до {format_number(MAX_BET)}:",
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
    db.add_balance(message.from_user.id, -bet, "game_bet", "Ставка в игре Алхимик")
    game = AlchemistGame(message.from_user.id, bet)
    registry.register(message.from_user.id, "alchemist", game)
    game.pick(first_pick)
    await state.clear()
    await message.answer(pick_text(game), reply_markup=ingredients_kb(game))


@router.callback_query(F.data.startswith("alch_brew:"), StateFilter("*"))
async def alchemist_brew(callback: CallbackQuery):
    user_id = callback.from_user.id
    game = registry.game(user_id)
    if not game or game.type != "alchemist":
        await callback.answer("Игра уже завершена.", show_alert=True)
        return
    mode = callback.data.split(":", 1)[1]
    if not game.choose_mode(mode):
        await callback.answer("Выбор недоступен. Проверьте ингредиенты.", show_alert=True)
        return

    # Settle before animation: /cancel during the animation cannot refund a known result.
    if game.success:
        result = cashout_game(user_id)
        final_text = win_text(game)
        level_msg = progress_text(result[2]) if result else ""
    else:
        result = lose_game(user_id)
        final_text = lose_text(game)
        level_msg = progress_text(result[1]) if result else ""
    await finish_mix(callback, game, final_text + level_msg)


async def finish_mix(callback: CallbackQuery, game, final_text: str) -> None:
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

    try:
        await callback.message.edit_text(final_text)
    except Exception:
        try:
            await callback.bot.send_message(callback.message.chat.id, final_text)
        except Exception:
            pass


@router.callback_query(F.data == "alch_cancel", StateFilter("*"))
async def alchemist_cancel(callback: CallbackQuery):
    game = cancel_game(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        "❌ Игра отменена. Ставка возвращена на баланс."
        if game else "Игра уже завершена. Возврата ставки нет."
    )
