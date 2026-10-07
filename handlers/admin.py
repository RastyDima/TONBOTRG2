from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from database import db
from keyboards.admin import admin_menu, admin_reset_kb
from keyboards.common import back_button, cancel_kb
from utils.helpers import format_number
from utils.notify import send as notify_send

router = Router()

PROMO_CODE_RE = r"[A-Za-z0-9_-]{1,32}"


class AdminStates(StatesGroup):
    give_user = State()
    give_amount = State()
    give_rubies_user = State()
    give_rubies_amount = State()
    give_title_user = State()
    give_title_select = State()
    block_user = State()
    unblock_user = State()


class AdminPromoStates(StatesGroup):
    code = State()
    amount = State()
    max_uses = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def resolve_user(text):
    text = (text or "").strip().lstrip("@")
    if not text:
        return None
    if text.isdigit():
        return db.get_user(int(text))
    return db.get_user_by_username(text)


def user_label(user: dict) -> str:
    return user["first_name"] or user["username"] or f"ID {user['id']}"


@router.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Доступ запрещён.")
        return
    await message.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "admin", StateFilter("*"))
async def admin_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещён.", show_alert=True)
        return
    await callback.message.edit_text("⚙️ <b>Админ-панель</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "admin_give", StateFilter("*"))
async def admin_give_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.give_user)
    await callback.answer()
    await callback.message.edit_text(
        "💰 <b>Выдача валюты</b>\n\nОтправьте ID или @username игрока:",
        reply_markup=cancel_kb(),
    )


@router.message(AdminStates.give_user)
async def admin_give_user(message: Message, state: FSMContext):
    user = resolve_user(message.text)
    if not user:
        await message.answer("❌ Пользователь не найден. Попробуйте ещё раз:")
        return
    await state.update_data(target_id=user["id"])
    await state.set_state(AdminStates.give_amount)
    await message.answer(
        f"Игрок: <b>{user_label(user)}</b> (ID: <code>{user['id']}</code>)\n\nВведите сумму:"
    )


@router.message(AdminStates.give_amount)
async def admin_give_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("target_id")
    text = (message.text or "").strip().replace(" ", "").replace(",", "")
    try:
        amount = int(text)
    except ValueError:
        await message.answer("❌ Некорректная сумма. Введите целое число:")
        return
    if amount < 0 or amount > 10_000_000_000:
        await message.answer("❌ Некорректная сумма.")
        return
    target = db.get_user(target_id)
    if not target:
        await state.clear()
        await message.answer("❌ Пользователь не найден.")
        return
    db.add_balance(target_id, amount, "admin", f"Выдача администратором {message.from_user.full_name}")
    await state.clear()
    latest = db.get_user(target_id)
    await notify_send(
        target_id,
        f"💰 <b>Вам начислено {format_number(amount)} TON</b>\n\n"
        f"💳 Баланс: {format_number(latest['balance'])}",
    )
    await message.answer(f"✅ Игроку <b>{user_label(target)}</b> начислено {format_number(amount)} TON.")


@router.callback_query(F.data == "admin_give_rubies", StateFilter("*"))
async def admin_give_rubies_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.give_rubies_user)
    await callback.answer()
    await callback.message.edit_text(
        "💎 <b>Выдача рубинов</b>\n\nОтправьте ID или @username игрока:",
        reply_markup=cancel_kb(),
    )


@router.message(AdminStates.give_rubies_user)
async def admin_give_rubies_user(message: Message, state: FSMContext):
    user = resolve_user(message.text)
    if not user:
        await message.answer("❌ Пользователь не найден. Попробуйте ещё раз:")
        return
    await state.update_data(target_id=user["id"])
    await state.set_state(AdminStates.give_rubies_amount)
    await message.answer(
        f"Игрок: <b>{user_label(user)}</b> (ID: <code>{user['id']}</code>)\n\n"
        f"💎 Текущие рубины: {user.get('rubies', 0) or 0}\n\n"
        f"Введите количество рубинов:"
    )


@router.message(AdminStates.give_rubies_amount)
async def admin_give_rubies_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("target_id")
    text = (message.text or "").strip().replace(" ", "").replace(",", ".")
    try:
        amount = float(text)
    except ValueError:
        await message.answer("❌ Некорректная сумма. Введите число:")
        return
    if amount < 0 or amount > 1_000_000:
        await message.answer("❌ Некорректная сумма.")
        return
    target = db.get_user(target_id)
    if not target:
        await state.clear()
        await message.answer("❌ Пользователь не найден.")
        return
    db.add_rubies(target_id, amount)
    await state.clear()
    latest = db.get_user(target_id)
    await notify_send(
        target_id,
        f"💎 <b>Вам начислено {amount} рубинов</b>\n\n"
        f"💎 Рубины: {latest.get('rubies', 0) or 0}",
    )
    await message.answer(f"✅ Игроку <b>{user_label(target)}</b> начислено {amount} 💎")


ALL_TITLES = [
    {"id": "title_spark", "name": "Собиратель искр"},
    {"id": "title_crystal", "name": "Искатель кристаллов"},
    {"id": "title_vip", "name": "Ловец удачи"},
    {"id": "title_elixir", "name": "Лунный алхимик"},
    {"id": "title_legend", "name": "Рисковый парень"},
    {"id": "title_shadow", "name": "Хранитель тайны"},
    {"id": "title_whale", "name": "Магнат"},
    {"id": "title_jackpot", "name": "Хранитель джекпота"},
    {"id": "title_god", "name": "Судьба"},
    {"id": "title_fortune", "name": "Архитектор фортуны"},
    {"id": "title_owner", "name": "Владелец"},
    {"id": "title_ket", "name": "Кет"},
    {"id": "title_from_ket", "name": "От Кета"},
    {"id": "title_girl", "name": "Девченка"},
    {"id": "title_huesos", "name": "Хуесос"},
]
TITLE_BY_ID = {t["id"]: t for t in ALL_TITLES}


def _title_list_kb():
    kb = InlineKeyboardBuilder()
    for t in ALL_TITLES:
        kb.button(text=t["name"], callback_data=f"admin_title_pick:{t['id']}")
    kb.row(back_button("admin"))
    kb.adjust(2)
    return kb.as_markup()


@router.callback_query(F.data == "admin_give_title", StateFilter("*"))
async def admin_give_title_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.give_title_user)
    await callback.answer()
    await callback.message.edit_text(
        "🏷 <b>Выдача титула</b>\n\nОтправьте ID или @username игрока:",
        reply_markup=cancel_kb(),
    )


@router.message(AdminStates.give_title_user)
async def admin_give_title_user(message: Message, state: FSMContext):
    user = resolve_user(message.text)
    if not user:
        await message.answer("❌ Пользователь не найден. Попробуйте ещё раз:")
        return
    await state.update_data(target_id=user["id"])
    await state.set_state(AdminStates.give_title_select)
    active = user.get("active_title") or "нет"
    await message.answer(
        f"Игрок: <b>{user_label(user)}</b> (ID: <code>{user['id']}</code>)\n\n"
        f"🏷 Текущий титул: <b>{active}</b>\n\n"
        f"Выберите титул для выдачи:",
        reply_markup=_title_list_kb(),
    )


@router.callback_query(F.data.startswith("admin_title_pick:"), AdminStates.give_title_select)
async def admin_title_pick(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_id")
    title_id = callback.data.split(":", 1)[1]
    title = TITLE_BY_ID.get(title_id)
    if not title:
        await callback.answer("❌ Титул не найден", show_alert=True)
        return
    target = db.get_user(target_id)
    if not target:
        await state.clear()
        await callback.message.edit_text("❌ Пользователь не найден.")
        return
    db.set_active_title(target_id, title_id)
    await state.clear()
    await notify_send(
        target_id,
        f"🏷 <b>Вам выдан титул: {title['name']}</b>",
    )
    await callback.message.edit_text(
        f"✅ Игроку <b>{user_label(target)}</b> выдан титул <b>{title['name']}</b>",
    )


@router.callback_query(F.data == "admin_block", StateFilter("*"))
async def admin_block_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.block_user)
    await callback.answer()
    await callback.message.edit_text(
        "🚫 <b>Блокировка</b>\n\nОтправьте ID или @username игрока:", reply_markup=cancel_kb()
    )


@router.message(AdminStates.block_user)
async def admin_block_user(message: Message, state: FSMContext):
    user = resolve_user(message.text)
    if not user:
        await message.answer("❌ Пользователь не найден. Попробуйте ещё раз:")
        return
    db.set_blocked(user["id"], True)
    await state.clear()
    await message.answer(f"🚫 Пользователь <b>{user_label(user)}</b> заблокирован.")


@router.callback_query(F.data == "admin_unblock", StateFilter("*"))
async def admin_unblock_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.unblock_user)
    await callback.answer()
    await callback.message.edit_text(
        "✅ <b>Разблокировка</b>\n\nОтправьте ID или @username игрока:", reply_markup=cancel_kb()
    )


@router.message(AdminStates.unblock_user)
async def admin_unblock_user(message: Message, state: FSMContext):
    user = resolve_user(message.text)
    if not user:
        await message.answer("❌ Пользователь не найден. Попробуйте ещё раз:")
        return
    db.set_blocked(user["id"], False)
    await state.clear()
    await message.answer(f"✅ Пользователь <b>{user_label(user)}</b> разблокирован.")


@router.callback_query(F.data == "admin_stats", StateFilter("*"))
async def admin_stats(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    data = db.admin_overview()
    kb = InlineKeyboardBuilder()
    kb.row(back_button("menu"))
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: {data['users']}\n"
        f"💰 Суммарный баланс: {format_number(data['balance'])} TON\n"
        f"🎮 Всего игр: {data['games']}\n"
        f"✅ Побед: {data['wins']}\n"
        f"📜 Транзакций: {data['tx_count']}\n"
        f"💸 Оборот: {format_number(data['tx_volume'])} TON",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "admin_reset", StateFilter("*"))
async def admin_reset_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещён.", show_alert=True)
        return
    await callback.message.edit_text(
        "🗑 <b>Сброс базы данных</b>\n\n"
        "Всем игрокам будет установлен стартовый баланс, "
        "статистика, история и активации промокодов будут удалены.\n"
        "Действие необратимо!\n\n"
        "Подтвердите:",
        reply_markup=admin_reset_kb(),
    )


@router.callback_query(F.data == "admin_reset_yes", StateFilter("*"))
async def admin_reset_yes(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔️ Доступ запрещён.", show_alert=True)
        return
    db.reset_database()
    await callback.answer("🗑 База данных сброшена!")
    await callback.message.edit_text("🗑 <b>База данных сброшена.</b>\n\nВсе балансы и статистика обнулены.")


@router.callback_query(F.data == "admin_reset_no", StateFilter("*"))
async def admin_reset_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("✅ Отменено.", reply_markup=admin_menu())


# ---------- Промокоды ----------

def promos_view() -> tuple[str, object]:
    promos = db.list_promos()
    lines = ["🎟 <b>Промокоды</b>\n"]
    if not promos:
        lines.append("Пока нет созданных промокодов.")
    for p in promos:
        state = "✅" if p["is_active"] else "⛔"
        lines.append(
            f"{state} <code>{p['code']}</code> · {format_number(p['amount'])} TON · "
            f"{p['used_count']}/{p['max_uses']} активаций"
        )
    text = "\n".join(lines)
    kb = InlineKeyboardBuilder()
    for p in promos:
        kb.button(text=f"🛠 {p['code']}", callback_data=f"promo_info:{p['id']}")
    if promos:
        kb.adjust(1)
    kb.button(text="➕ Создать промокод", callback_data="admin_promo_create")
    kb.button(text="◀️ Назад", callback_data="admin")
    kb.adjust(1)
    return text, kb.as_markup()


@router.callback_query(F.data == "admin_promos", StateFilter("*"))
async def admin_promos(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    text, kb = promos_view()
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("promo_info:"), StateFilter("*"))
async def promo_info(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    pid = int(callback.data.split(":", 1)[1])
    p = db.get_promo_by_id(pid)
    if not p:
        await callback.answer("Промокод не найден", show_alert=True)
        return
    state_label = "активен" if p["is_active"] else "неактивен"
    text = (
        f"🎟 <b>Промокод {p['code']}</b>\n\n"
        f"💰 Сумма: {format_number(p['amount'])} TON\n"
        f"🔢 Активаций: {p['used_count']}/{p['max_uses']}\n"
        f"📌 Статус: {state_label}\n"
        f"📅 Создан: {p['created_at']}"
    )
    kb = InlineKeyboardBuilder()
    if p["is_active"]:
        kb.button(text="⛔ Деактивировать", callback_data=f"promo_toggle:{pid}")
    else:
        kb.button(text="✅ Активировать", callback_data=f"promo_toggle:{pid}")
    kb.button(text="🗑 Удалить", callback_data=f"promo_del:{pid}")
    kb.button(text="◀️ Назад", callback_data="admin_promos")
    kb.adjust(2)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("promo_toggle:"), StateFilter("*"))
async def promo_toggle(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    pid = int(callback.data.split(":", 1)[1])
    p = db.get_promo_by_id(pid)
    if p:
        db.toggle_promo(pid, not p["is_active"])
    await callback.answer()
    text, kb = promos_view()
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("promo_del:"), StateFilter("*"))
async def promo_delete(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    pid = int(callback.data.split(":", 1)[1])
    db.delete_promo(pid)
    await callback.answer("Промокод удалён", show_alert=True)
    text, kb = promos_view()
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "admin_promo_create", StateFilter("*"))
async def promo_create_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminPromoStates.code)
    await callback.answer()
    await callback.message.edit_text(
        "🎟 <b>Создание промокода</b>\n\n"
        "Введите код (буквы/цифры, до 32 символов). Игрок будет вводить его как <code>#КОД</code>:",
        reply_markup=cancel_kb(),
    )


@router.message(AdminPromoStates.code)
async def promo_create_code(message: Message, state: FSMContext):
    import re

    code = (message.text or "").strip()
    if not re.fullmatch(PROMO_CODE_RE, code):
        await message.answer("❌ Некорректный код. Только буквы, цифры, _ и -, до 32 символов:")
        return
    await state.update_data(promo_code=code.upper())
    await state.set_state(AdminPromoStates.amount)
    await message.answer("💵 Введите сумму TON за активацию:")


@router.message(AdminPromoStates.amount)
async def promo_create_amount(message: Message, state: FSMContext):
    try:
        amount = int((message.text or "").strip().replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("❌ Некорректная сумма. Введите целое число:")
        return
    if amount <= 0 or amount > 10 ** 12:
        await message.answer("❌ Сумма должна быть больше 0 и не больше 1 000 000 000 000:")
        return
    await state.update_data(promo_amount=amount)
    await state.set_state(AdminPromoStates.max_uses)
    await message.answer("🔢 Максимум активаций (целое число от 1):")


@router.message(AdminPromoStates.max_uses)
async def promo_create_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int((message.text or "").strip().replace(" ", "").replace(",", ""))
    except ValueError:
        await message.answer("❌ Некорректное число. Введите целое число от 1:")
        return
    if max_uses < 1 or max_uses > 10 ** 6:
        await message.answer("❌ Максимум активаций должен быть от 1 до 1 000 000:")
        return
    data = await state.get_data()
    ok = db.create_promo(data["promo_code"], data["promo_amount"], max_uses)
    await state.clear()
    if ok:
        await message.answer(
            f"✅ Промокод <code>#{data['promo_code']}</code> создан:\n"
            f"💰 {format_number(data['promo_amount'])} TON · 🔢 {max_uses} активаций"
        )
    else:
        await message.answer(
            f"❌ Промокод <code>{data['promo_code']}</code> уже существует.",
            reply_markup=cancel_kb(),
        )
