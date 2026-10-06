from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from keyboards.common import back_button
from utils.helpers import rating_text

router = Router()


def rating_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 По максимуму", callback_data="rating_balance")
    kb.button(text="🎯 По победам", callback_data="rating_wins")
    kb.button(text="📊 По опыту", callback_data="rating_xp")
    kb.adjust(3)
    kb.button(text="🏆 Неделя", callback_data="rating_period:week")
    kb.button(text="🏆 Месяц", callback_data="rating_period:month")
    kb.adjust(3, 2)
    kb.row(back_button("menu"))
    return kb.as_markup()


@router.message(Command("rating"))
async def rating_command(message: Message):
    top = db.player_leaderboard(0, "balance", "all", 10)["players"]
    await message.answer(rating_text(top, "balance"), reply_markup=rating_kb())


@router.callback_query(F.data == "rating", StateFilter("*"))
async def rating_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    top = db.player_leaderboard(0, "balance", "all", 10)["players"]
    await callback.message.edit_text(rating_text(top, "balance"), reply_markup=rating_kb())


@router.callback_query(F.data.in_({"rating_balance", "rating_wins", "rating_xp"}), StateFilter("*"))
async def rating_switch(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    if callback.data == "rating_balance":
        top = db.player_leaderboard(0, "balance", "all", 10)["players"]
        mode = "balance"
    elif callback.data == "rating_xp":
        top = db.player_leaderboard(0, "xp", "all", 10)["players"]
        mode = "xp"
    else:
        top = db.player_leaderboard(0, "wins", "all", 10)["players"]
        mode = "wins"
    await callback.message.edit_text(rating_text(top, mode), reply_markup=rating_kb())


@router.callback_query(F.data.startswith("rating_period:"), StateFilter("*"))
async def rating_period(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":", 1)[1]
    if period not in ("week", "month"):
        await callback.answer("Неизвестный период", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    top = db.player_leaderboard(callback.from_user.id, "wins", period, 10)
    title = "за неделю" if period == "week" else "за месяц"
    own = f"\n\nВаше место: <b>#{top['my_rank']}</b>" if top["my_rank"] else ""
    await callback.message.edit_text(f"🗓 <b>Рейтинг {title}</b>\n\n" + rating_text(top["players"], "wins") + own,
                                     reply_markup=rating_kb())
