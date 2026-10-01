import html

from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS, STARTING_BALANCE
from database import db, level_info, level_name
from keyboards.main_menu import main_menu
from mobile_pairing import claim_pairing
from utils.game_registry import cancel_game, clear_pending_bet, registry
from utils.helpers import format_number, menu_text

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    existing = db.get_user(user.id)
    referrer_id = None
    args = (message.text or "").split()
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            referrer_id = int(args[1][3:])
        except ValueError:
            pass
    if existing:
        db.register_user(user.id, (user.username or "").lower() or None, user.first_name)
    else:
        db.register_user(user.id, (user.username or "").lower() or None, user.first_name, referrer_id)
        db.add_xp(user.id, 10)
        if referrer_id and referrer_id != user.id:
            db.add_xp(referrer_id, 100)
        from utils.achievements import check_achievements
        check_achievements(user.id)
        if referrer_id and referrer_id != user.id:
            check_achievements(referrer_id)
    name = html.escape(user.first_name or "игрок")
    if existing:
        text = f"👋 С возвращением, {name}!\nВыберите действие в меню:"
    elif referrer_id:
        ref = db.get_user(referrer_id)
        ref_name = html.escape(ref["first_name"]) if ref else "игрок"
        text = (
            f"👋 <b>Добро пожаловать, {name}!</b>\n\n"
            f"🎁 За регистрацию начислено {format_number(STARTING_BALANCE)} TON.\n"
            f"👋 Вас пригласил {ref_name}\n\n"
            f"Выберите действие в меню:"
        )
    else:
        text = (
            f"👋 <b>Добро пожаловать, {name}!</b>\n\n"
            f"🎁 За регистрацию начислено {format_number(STARTING_BALANCE)} TON.\n\n"
            f"Выберите действие в меню:"
        )
    is_admin = user.id in ADMIN_IDS or bool(db.get_user(user.id)["is_admin"])
    if len(args) > 1 and args[1].startswith("app_"):
        paired = claim_pairing(args[1][4:], user.id)
        await message.answer(
            "✅ Аккаунт подключён. Вернитесь в Android-приложение."
            if paired else "⌛ Код приложения устарел. Получите новый код в приложении.",
            reply_markup=main_menu(is_admin),
        )
        return
    await message.answer(text, reply_markup=main_menu(is_admin))


@router.message(Command("connect"))
async def connect_android(message: Message):
    if message.chat.type != "private":
        await message.answer("Подключайте приложение в личном чате с ботом.")
        return
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала используйте /start.")
        return
    parts = (message.text or "").split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not claim_pairing(code, user["id"]):
        await message.answer("⌛ Код приложения неверный или устарел. Получите новый код в приложении.")
        return
    await message.answer("✅ Аккаунт подключён. Вернитесь в Android-приложение.")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Помощь</b>\n\n"
        "🎮 <b>Игры:</b> Мины, Джокер, Алхимик, Монетка, 21 (доступны из меню)\n"
        "⚡ <b>Быстрый старт:</b>\n"
        "<code>м 30000</code> — мины\n"
        "<code>дж 30000</code> — джокер\n"
        "<code>алх 30000</code> — алхимик\n"
        "<code>мон 30000</code> — монетка\n"
        "<code>21 30000</code> — карточная игра 21\n"
        "💸 <b>Перевод:</b> ответьте на сообщение игрока <code>п 12000</code>\n"
        "💰 <b>Баланс:</b> <code>б</code>\n"
        "👤 /profile — профиль и статистика\n"
        "📊 /level — ваш уровень и прогресс\n"
        "🏅 /achievements — достижения\n"
        "🎁 /daily — ежедневный бонус\n"
        "🗓 /weekly — еженедельный бонус\n"
        "🎟 Промокод: введите <code>#КОД</code> в чате\n"
        "📜 /history — история транзакций\n"
        "🏆 /rating — рейтинг игроков\n"
        "❌ /cancel — отменить действие или выйти из игры\n\n"
        "Все действия доступны через кнопки меню."
    )


@router.callback_query(F.data == "menu", StateFilter("*"))
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    clear_pending_bet(callback.from_user.id)
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("Используйте /start")
        return
    is_admin = callback.from_user.id in ADMIN_IDS or bool(user["is_admin"])
    try:
        await callback.message.edit_text(menu_text(user), reply_markup=main_menu(is_admin))
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(menu_text(user), reply_markup=main_menu(is_admin))


@router.callback_query(F.data == "cancel", StateFilter("*"))
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    active = registry.game(callback.from_user.id)
    refunded = cancel_game(callback.from_user.id)
    await callback.answer()
    text = ("❌ Игра завершена. Ставка проиграна." if active and not refunded
            else "❌ Игра отменена. Ставка возвращена." if refunded
            else "❌ Действие отменено.")
    await callback.message.edit_text(text)


@router.message(Command("cancel"), StateFilter("*"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    if registry.game(message.from_user.id):
        refunded = cancel_game(message.from_user.id)
        await message.answer(
            "❌ Игра отменена. Ставка возвращена на баланс."
            if refunded else "❌ Игра завершена. Ставка проиграна."
        )
    else:
        await message.answer("❌ Отменено.")


@router.message(Command("level"))
async def level_command(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    xp = user.get("xp", 0) or 0
    li = level_info(xp)
    name = level_name(li["level"])
    bar_len = 20
    filled = int(li["progress"] * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    await message.answer(
        f"📊 <b>Уровень</b>\n\n"
        f"Уровень: <b>{li['level']}</b> — {name}\n"
        f"XP: <b>{li['xp']}</b> / {li['next_level_xp']}\n"
        f"<code>{bar}</code> {int(li['progress'] * 100)}%\n\n"
        f"До следующего уровня: <b>{li['next_level_xp'] - li['xp']}</b> XP"
    )
