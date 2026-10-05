from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import asyncio
import logging
from database import db
from keyboards.common import back_button
from utils.helpers import balance_text
from utils.profile_card import generate_profile_card
from utils.achievement_card import generate_achievements_card
from utils.achievements import ACHIEVEMENTS
from utils.avatars import AvatarUnavailable, get_avatar

router = Router()
log = logging.getLogger(__name__)


def profile_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏅 Достижения", callback_data="achievements")
    kb.row(back_button("menu"))
    return kb.as_markup()


def balance_kb():
    kb = InlineKeyboardBuilder()
    kb.row(
        back_button("menu"),
    )
    return kb.as_markup()


async def _get_avatar(user_id: int) -> tuple[bytes | None, bool]:
    try:
        avatar = await get_avatar(user_id)
    except AvatarUnavailable:
        return None, False
    return (avatar.data, avatar.content_type == "image/gif") if avatar else (None, False)

async def _make_card(user, stats, ref_count, from_user, frame_override=None):
    avatar_bytes, _ = await _get_avatar(user["id"])
    ach_count = len(db.get_achievements(user["id"]))
    from utils.achievements import TOTAL as ACH_TOTAL
    showcase = [ACHIEVEMENTS[award_id]["name"] for award_id in db.get_showcase(user["id"])
                if award_id in ACHIEVEMENTS]
    card_buf = await asyncio.to_thread(generate_profile_card,
        user_id=user["id"],
        name=user["first_name"] or "Игрок",
        balance=user["balance"],
        rubies=user.get("rubies", 0) or 0,
        total_games=stats["total_games"],
        wins=stats["wins"],
        losses=stats["losses"],
        total_bet=stats["total_bet"],
        total_won=stats["total_won"],
        ref_count=ref_count,
        avatar_bytes=avatar_bytes,
        frame=frame_override or user.get("active_frame"),
        title=user.get("active_title"),
        xp=user.get("xp", 0) or 0,
        ach_count=ach_count,
        ach_total=ACH_TOTAL,
        showcase=showcase,
    )
    is_gif = card_buf.getvalue()[:6] in (b"GIF87a", b"GIF89a")
    ext = "gif" if is_gif else "png"
    return (f"profile.{ext}", card_buf.getvalue())


async def _send_profile_card(message, filename, data):
    media = BufferedInputFile(data, filename=filename)
    if data.startswith((b"GIF87a", b"GIF89a")):
        await message.answer_animation(animation=media, reply_markup=profile_kb())
    else:
        await message.answer_photo(photo=media, reply_markup=profile_kb())


@router.message(Command("profile"))
async def profile_command(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    stats = db.get_stats(message.from_user.id)
    ref_count = user.get("referral_count", 0) or 0
    filename, data = await _make_card(user, stats, ref_count, message.from_user)
    await _send_profile_card(message, filename, data)


@router.callback_query(F.data == "profile", StateFilter("*"))
async def profile_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("Используйте /start")
        return
    stats = db.get_stats(callback.from_user.id)
    ref_count = user.get("referral_count", 0) or 0
    filename, data = await _make_card(user, stats, ref_count, callback.from_user)
    await _send_profile_card(callback.message, filename, data)
    try:
        await callback.message.delete()
    except Exception:
        pass



@router.callback_query(F.data == "balance", StateFilter("*"))
async def balance_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("Используйте /start")
        return
    await callback.message.edit_text(balance_text(user), reply_markup=balance_kb())


def _ach_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Настроить витрину", callback_data="showcase")
    kb.row(back_button("profile"))
    return kb.as_markup()


def _showcase_kb(user_id: int):
    owned = set(db.get_achievements(user_id))
    selected = set(db.get_showcase(user_id))
    kb = InlineKeyboardBuilder()
    for award_id, award in ACHIEVEMENTS.items():
        if award_id in owned:
            mark = "✅" if award_id in selected else "➕"
            kb.button(text=f"{mark} {award['name']}", callback_data=f"showcase_toggle:{award_id}")
    kb.button(text="◀ К достижениям", callback_data="achievements")
    kb.adjust(1)
    return kb.as_markup()


def _showcase_text(user_id: int) -> str:
    count = len(db.get_showcase(user_id))
    if not db.get_achievements(user_id):
        return "✨ <b>Витрина наград</b>\n\nПока нет полученных достижений. Сыграйте первую игру, чтобы открыть награду."
    return (f"✨ <b>Витрина наград</b> · {count}/3\n\n"
            "Выберите до трёх полученных достижений. Они появятся на карточке профиля.")


@router.callback_query(F.data == "showcase", StateFilter("*"))
async def showcase_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    if not db.get_user(callback.from_user.id):
        await callback.message.answer("Сначала нажмите /start")
        return
    await callback.message.answer(
        _showcase_text(callback.from_user.id),
        reply_markup=_showcase_kb(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("showcase_toggle:"), StateFilter("*"))
async def showcase_toggle_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    award_id = callback.data.split(":", 1)[1]
    if award_id not in ACHIEVEMENTS:
        await callback.answer("Достижение не найдено", show_alert=True)
        return
    result = db.toggle_showcase(callback.from_user.id, award_id)
    if result == "full":
        await callback.answer("Сначала уберите одну из трёх наград", show_alert=True)
        return
    if result == "not_earned":
        await callback.answer("Это достижение ещё не получено", show_alert=True)
        return
    await callback.answer("Витрина обновлена")
    await callback.message.edit_text(
        _showcase_text(callback.from_user.id),
        reply_markup=_showcase_kb(callback.from_user.id),
    )


async def _send_achievements_card(message: Message, user: dict) -> bool:
    try:
        owned = db.get_achievements(user["id"])
        card = await asyncio.to_thread(
            generate_achievements_card,
            user_id=user["id"],
            name=user["first_name"] or "Игрок",
            owned=owned,
        )
        photo = BufferedInputFile(
            card.getvalue(), filename=f"achievements_{user['id']}.png"
        )
        await message.answer_photo(photo=photo, reply_markup=_ach_kb())
    except Exception:
        log.exception("Failed to send achievements card for %s", user["id"])
        await message.answer(
            "Не удалось загрузить карточку достижений. Попробуйте ещё раз чуть позже."
        )
        return False
    return True


@router.message(Command("achievements"))
async def achievements_command(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    await _send_achievements_card(message, user)


@router.callback_query(F.data == "achievements", StateFilter("*"))
async def achievements_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.message.answer("Используйте /start")
        return
    if not await _send_achievements_card(callback.message, user):
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
