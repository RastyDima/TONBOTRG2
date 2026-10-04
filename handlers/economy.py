from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from keyboards.economy import bonuses_kb, history_kb, reminders_kb
from utils.economy_views import HISTORY_LABELS, bonuses_text, history_page, reminders_text
from utils.game_registry import award_progress, progress_text
from keyboards.common import back_button
from utils.helpers import (
    balance_text,
    format_number,
    get_daily_bonus,
    get_weekly_bonus,
    quick_command,
)
from utils.notify import send as notify_send

router = Router()

TRANSFER_COMMANDS = ("п", "перевод", "перевести", "transfer")
BALANCE_COMMANDS = ("б", "баланс", "balance", "balance")
TRANSFER_MAX = 10 ** 15


def is_balance(message: Message) -> bool:
    return quick_command(message.text, BALANCE_COMMANDS) is not None


def is_transfer(message: Message) -> bool:
    return quick_command(message.text, TRANSFER_COMMANDS, max_bet=TRANSFER_MAX) is not None


def back_kb():
    kb = InlineKeyboardBuilder()
    kb.row(back_button("menu"))
    return kb.as_markup()


XP_DAILY = 15
XP_WEEKLY = 50


async def _edit_screen(callback: CallbackQuery, text: str, markup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def _bonus_screen(user_id: int, kind: str | None = None):
    user = db.get_user(user_id)
    if not user:
        return "Сначала нажмите /start", None
    notice = ""
    if kind:
        amount = get_daily_bonus() if kind == "daily" else get_weekly_bonus()
        claim = db.claim_daily if kind == "daily" else db.claim_weekly
        if claim(user_id, amount):
            xp = XP_DAILY if kind == "daily" else XP_WEEKLY
            notice = (f"✅ Получено <b>{format_number(amount)} TON</b>."
                      + progress_text(award_progress(user_id, xp)))
        else:
            notice = "⏳ Этот бонус уже получен."
        user = db.get_user(user_id)
    return bonuses_text(user, get_daily_bonus(), get_weekly_bonus(), notice), bonuses_kb(user)


@router.message(Command("bonuses", "daily", "weekly"))
async def bonuses_command(message: Message, state: FSMContext):
    await state.clear()
    command = (message.text or "").split()[0].split("@")[0].lstrip("/")
    kind = command if command in ("daily", "weekly") else None
    text, markup = _bonus_screen(message.from_user.id, kind)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.in_({"bonuses", "daily", "weekly"}), StateFilter("*"))
async def bonuses_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    kind = callback.data if callback.data in ("daily", "weekly") else None
    text, markup = _bonus_screen(callback.from_user.id, kind)
    await _edit_screen(callback, text, markup)


@router.message(Command("reminders"))
async def reminders_command(message: Message, state: FSMContext):
    await state.clear()
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    await message.answer(reminders_text(user), reply_markup=reminders_kb(user))


@router.callback_query(F.data == "reminders", StateFilter("*"))
async def reminders_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    if not user:
        await _edit_screen(callback, "Сначала нажмите /start", None)
        return
    await _edit_screen(callback, reminders_text(user), reminders_kb(user))


@router.callback_query(F.data.startswith("reminder:"), StateFilter("*"))
async def reminder_toggle(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[1] not in ("daily", "weekly") or parts[2] not in ("0", "1"):
        await callback.answer("Неизвестная настройка", show_alert=True)
        return
    await state.clear()
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    db.set_bonus_reminder(user["id"], parts[1], parts[2] == "1")
    await callback.answer("Настройки сохранены")
    user = db.get_user(user["id"])
    await _edit_screen(callback, reminders_text(user), reminders_kb(user))


@router.message(Command("history"))
async def history_command(message: Message, state: FSMContext):
    await state.clear()
    if not db.get_user(message.from_user.id):
        await message.answer("Сначала нажмите /start")
        return
    view = history_page(db, message.from_user.id)
    await message.answer(view["text"], reply_markup=history_kb(
        view["category"], view["page"], view["pages"], view["anchor"],
    ))


@router.callback_query(
    (F.data == "history") | F.data.startswith("history:") | F.data.startswith("history_refresh:"),
    StateFilter("*"),
)
async def history_callback(callback: CallbackQuery, state: FSMContext):
    category, page, anchor = "all", 0, None
    try:
        if callback.data.startswith("history_refresh:"):
            category = callback.data.split(":", 1)[1]
        elif callback.data.startswith("history:"):
            _, category, page_text, anchor_text = callback.data.split(":")
            page, anchor = int(page_text), int(anchor_text)
            if page < 0 or not 0 <= anchor <= 2 ** 63 - 1:
                raise ValueError
        if category not in HISTORY_LABELS:
            raise ValueError
    except (ValueError, TypeError):
        await callback.answer("Откройте историю заново через /history", show_alert=True)
        return
    await state.clear()
    if not db.get_user(callback.from_user.id):
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    await callback.answer()
    view = history_page(db, callback.from_user.id, category, page, anchor)
    await _edit_screen(callback, view["text"], history_kb(
        view["category"], view["page"], view["pages"], view["anchor"],
    ))


@router.callback_query(F.data == "history_page", StateFilter("*"))
async def history_page_info(callback: CallbackQuery):
    await callback.answer("Листайте историю кнопками «Назад» и «Далее».")


@router.message(F.text, is_balance)
async def balance_quick(message: Message, state: FSMContext):
    await state.clear()
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    await message.answer(balance_text(user))


@router.message(F.text, is_transfer)
async def transfer_money(message: Message, state: FSMContext):
    info = quick_command(message.text, TRANSFER_COMMANDS, max_bet=TRANSFER_MAX)
    amount = info["bet"]
    if amount is None:
        await message.answer(
            "💸 <b>Перевод</b>\nОтветьте на сообщение игрока: <code>п 12000</code>\n"
            "Например: <code>п 5к</code>, <code>п 1.5м</code>"
        )
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer(
            "💸 <b>Перевод</b>\nОтветьте на сообщение игрока, которому хотите перевести:\n"
            "<code>п 12000</code>"
        )
        return
    sender = message.from_user
    receiver = message.reply_to_message.from_user
    if receiver.id == sender.id:
        await message.answer("❌ Нельзя переводить самому себе.")
        return
    rec = db.get_user(receiver.id)
    if not rec:
        await message.answer("❌ Получатель не найден. Игрок должен нажать /start.")
        return
    sender_db = db.get_user(sender.id)
    if not sender_db:
        await message.answer("Сначала нажмите /start")
        return
    if amount > sender_db["balance"]:
        await message.answer(
            f"❌ Недостаточно средств. Баланс: {format_number(sender_db['balance'])}"
        )
        return
    await state.clear()
    db.add_balance(sender.id, -amount, "transfer_out", f"Перевод игроку {receiver.full_name}")
    db.add_balance(receiver.id, amount, "transfer_in", f"Перевод от игрока {sender.full_name}")
    latest = db.get_user(receiver.id)
    await notify_send(
        receiver.id,
        f"💸 <b>Перевод получен</b>\n\n"
        f"Игрок {sender.full_name} перевёл вам <b>{format_number(amount)}</b> TON.\n"
        f"💳 Баланс: {format_number(latest['balance'])}",
    )
    await message.answer(
        f"✅ Переведено <b>{format_number(amount)}</b> TON игроку {receiver.full_name}.\n"
        f"💰 Ваш баланс: {format_number(sender_db['balance'] - amount)}"
    )
