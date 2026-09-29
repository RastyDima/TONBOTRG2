from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from keyboards.common import back_button

router = Router()
FRAMES_GALLERY = Path(__file__).resolve().parent.parent / "assets" / "frames_gallery.png"

SHOP_ITEMS = {
    "frames": [
        {"id": "frame_neon_green", "name": "Неоновый контур", "price": 500_000, "color": (0, 255, 120)},
        {"id": "frame_fire_red", "name": "Инферно", "price": 750_000, "color": (255, 60, 40)},
        {"id": "frame_ice_blue", "name": "Ледяные осколки", "price": 1_000_000, "color": (60, 180, 255)},
        {"id": "frame_gold", "name": "Золотая корона", "price": 2_000_000, "color": (255, 210, 60)},
        {"id": "frame_diamond", "name": "Алмазная призма", "price": 5_000_000, "color": (180, 230, 255)},
    ],
    "titles": [
        {"id": "title_vip", "name": "VIP", "price": 1_000_000},
        {"id": "title_legend", "name": "Legend", "price": 3_000_000},
        {"id": "title_whale", "name": "Whale", "price": 5_000_000},
        {"id": "title_god", "name": "God", "price": 10_000_000},
    ],
    "exclusive_titles": [
        {"id": "title_owner", "name": "Владелец"},
        {"id": "title_ket", "name": "Кет"},
    ],
}

FRAME_BY_ID = {item["id"]: item for item in SHOP_ITEMS["frames"]}
TITLE_BY_ID = {item["id"]: item for item in SHOP_ITEMS["titles"]}
ALL_BY_ID = {**FRAME_BY_ID, **TITLE_BY_ID}


def _format_price(price: int) -> str:
    return f"{price:,}".replace(",", " ")


def shop_main_kb(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🖼 Рамки профиля", callback_data="shop_frames")
    kb.button(text="🏷 Титулы", callback_data="shop_titles")
    kb.button(text="🎒 Мои покупки", callback_data="shop_my")
    kb.row(back_button("menu"))
    kb.adjust(1)
    return kb.as_markup()


def shop_category_kb(category: str, items: list, user_id: int):
    kb = InlineKeyboardBuilder()
    for item in items:
        owned = db.owns_item(user_id, item["id"])
        if owned:
            label = f"✅ {item['name']} — уже есть"
        else:
            label = f"{item['name']} — {_format_price(item['price'])} TON"
        kb.button(text=label, callback_data=f"shop_buy:{item['id']}")
    if category == "frames":
        kb.button(text="👁 Посмотреть рамки", callback_data="shop_frames_preview")
    kb.button(text="◀ Назад", callback_data="shop")
    kb.adjust(1)
    return kb.as_markup()


def equip_kb(items: list, category: str, user_id: int):
    kb = InlineKeyboardBuilder()
    for item in items:
        kb.button(text=f"🟢 {item['name']}", callback_data=f"shop_equip:{item['id']}")
    kb.button(text="❌ Снять", callback_data=f"shop_unequip:{category}")
    kb.button(text="◀ Назад", callback_data="shop")
    kb.adjust(1)
    return kb.as_markup()


@router.message(Command("shop"))
async def shop_command(message: Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return
    balance = user.get("balance", 0)
    await message.answer(
        f"🏪 <b>Магазин</b>\n\n"
        f"💰 Ваш баланс: <b>{_format_price(balance)} TON</b>\n\n"
        f"Выберите категорию:",
        reply_markup=shop_main_kb(message.from_user.id),
    )


@router.callback_query(F.data == "shop", StateFilter("*"))
async def shop_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("Используйте /start")
        return
    balance = user.get("balance", 0)
    await callback.message.edit_text(
        f"🏪 <b>Магазин</b>\n\n"
        f"💰 Ваш баланс: <b>{_format_price(balance)} TON</b>\n\n"
        f"Выберите категорию:",
        reply_markup=shop_main_kb(callback.from_user.id),
    )


@router.callback_query(F.data == "shop_frames", StateFilter("*"))
async def shop_frames_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    balance = user.get("balance", 0) if user else 0
    active = user.get("active_frame") if user else None
    text = f"🖼 <b>Рамки профиля</b>\n\n💰 Баланс: <b>{_format_price(balance)} TON</b>"
    if active:
        item = FRAME_BY_ID.get(active)
        name = item["name"] if item else active
        text += f"\n🟢 Активная: <b>{name}</b>"
    text += "\n\nВыберите рамку для покупки:"
    await callback.message.edit_text(text, reply_markup=shop_category_kb(
        "frames", SHOP_ITEMS["frames"], callback.from_user.id,
    ))


@router.callback_query(F.data == "shop_frames_preview", StateFilter("*"))
async def shop_frames_preview_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer_photo(
        photo=FSInputFile(FRAMES_GALLERY),
        caption="🖼 Рамки на карточке профиля. Выберите понравившуюся в меню магазина выше.",
    )


@router.callback_query(F.data == "shop_titles", StateFilter("*"))
async def shop_titles_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    balance = user.get("balance", 0) if user else 0
    active = user.get("active_title") if user else None
    text = f"🏷 <b>Титулы</b>\n\n💰 Баланс: <b>{_format_price(balance)} TON</b>"
    if active:
        item = TITLE_BY_ID.get(active)
        name = item["name"] if item else active
        text += f"\n🟢 Активный: <b>{name}</b>"
    text += "\n\nВыберите титул для покупки:"
    await callback.message.edit_text(text, reply_markup=shop_category_kb(
        "titles", SHOP_ITEMS["titles"], callback.from_user.id,
    ))


@router.callback_query(F.data.startswith("shop_buy:"), StateFilter("*"))
async def shop_buy_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    item_id = callback.data.split(":", 1)[1]
    item = ALL_BY_ID.get(item_id)
    if not item:
        await callback.answer("❌ Товар не найден", show_alert=True)
        return

    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("Используйте /start")
        return

    if db.owns_item(callback.from_user.id, item_id):
        await callback.answer("✅ Уже куплено! Используйте «Мои покупки»", show_alert=True)
        return

    if user.get("balance", 0) < item["price"]:
        await callback.answer(
            f"❌ Недостаточно TON.\nНужно: {_format_price(item['price'])}\nУ вас: {_format_price(user.get('balance', 0))}",
            show_alert=True,
        )
        return

    ok = db.buy_item(callback.from_user.id, item_id, "frame" if item_id.startswith("frame") else "title", item["price"])
    if ok:
        user = db.get_user(callback.from_user.id)
        balance = user.get("balance", 0)
        category = "frames" if item_id.startswith("frame") else "titles"
        cat_label = "Рамки профиля" if category == "frames" else "Титулы"
        await callback.message.edit_text(
            f"✅ <b>Покупка успешна!</b>\n\n"
            f"Куплено: <b>{item['name']}</b>\n"
            f"Списано: {_format_price(item['price'])} TON\n"
            f"💰 Баланс: <b>{_format_price(balance)} TON</b>\n\n"
            f"Теперь вы можете активировать товар в «Мои покупки».",
            reply_markup=shop_category_kb(category, SHOP_ITEMS[category], callback.from_user.id),
        )
    else:
        await callback.answer("❌ Ошибка покупки", show_alert=True)


@router.callback_query(F.data == "shop_my", StateFilter("*"))
async def shop_my_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    if not user:
        await callback.message.edit_text("Используйте /start")
        return

    purchases = db.get_purchases(callback.from_user.id)
    frames_owned = [p for p in purchases if p["category"] == "frame"]
    titles_owned = [p for p in purchases if p["category"] == "title"]

    text = "🎒 <b>Мои покупки</b>\n\n"

    active_frame = user.get("active_frame")
    active_title = user.get("active_title")

    if frames_owned:
        text += "🖼 <b>Рамки:</b>\n"
        for p in frames_owned:
            item = FRAME_BY_ID.get(p["item_id"])
            name = item["name"] if item else p["item_id"]
            status = "🟢" if active_frame == p["item_id"] else "⚪"
            text += f"  {status} {name}\n"
    else:
        text += "🖼 Рамок нет\n"

    if titles_owned:
        text += "\n🏷 <b>Титулы:</b>\n"
        for p in titles_owned:
            item = TITLE_BY_ID.get(p["item_id"])
            name = item["name"] if item else p["item_id"]
            status = "🟢" if active_title == p["item_id"] else "⚪"
            text += f"  {status} {name}\n"
    else:
        text += "\n🏷 Титулов нет\n"

    text += "\n🟢 — активно  ⚪ — не активно"

    kb = InlineKeyboardBuilder()
    if frames_owned:
        kb.button(text="🖼 Выбрать рамку", callback_data="shop_equip_frames")
    if titles_owned:
        kb.button(text="🏷 Выбрать титул", callback_data="shop_equip_titles")
    kb.button(text="◀ Назад", callback_data="shop")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "shop_equip_frames", StateFilter("*"))
async def shop_equip_frames_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    purchases = db.get_purchases(callback.from_user.id) if user else []
    frames_owned = [p for p in purchases if p["category"] == "frame"]
    items = [FRAME_BY_ID[p["item_id"]] for p in frames_owned if p["item_id"] in FRAME_BY_ID]
    if not items:
        await callback.answer("Нет рамок", show_alert=True)
        return
    await callback.message.edit_text(
        "🖼 <b>Выберите рамку:</b>",
        reply_markup=equip_kb(items, "frames", callback.from_user.id),
    )


@router.callback_query(F.data == "shop_equip_titles", StateFilter("*"))
async def shop_equip_titles_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    user = db.get_user(callback.from_user.id)
    purchases = db.get_purchases(callback.from_user.id) if user else []
    titles_owned = [p for p in purchases if p["category"] == "title"]
    items = [TITLE_BY_ID[p["item_id"]] for p in titles_owned if p["item_id"] in TITLE_BY_ID]
    if not items:
        await callback.answer("Нет титулов", show_alert=True)
        return
    await callback.message.edit_text(
        "🏷 <b>Выберите титул:</b>",
        reply_markup=equip_kb(items, "titles", callback.from_user.id),
    )


@router.callback_query(F.data.startswith("shop_equip:"), StateFilter("*"))
async def shop_equip_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    item_id = callback.data.split(":", 1)[1]

    if item_id.startswith("frame"):
        db.set_active_frame(callback.from_user.id, item_id)
        await callback.answer("🟢 Рамка активирована!", show_alert=True)
    elif item_id.startswith("title"):
        db.set_active_title(callback.from_user.id, item_id)
        await callback.answer("🟢 Титул активирован!", show_alert=True)
    else:
        await callback.answer("❌ Неизвестный товар", show_alert=True)
        return

    await shop_my_callback(callback, state)


@router.callback_query(F.data.startswith("shop_unequip:"), StateFilter("*"))
async def shop_unequip_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    category = callback.data.split(":", 1)[1]
    if category == "frames":
        db.set_active_frame(callback.from_user.id, None)
        await callback.answer("Рамка снята", show_alert=True)
    elif category == "titles":
        db.set_active_title(callback.from_user.id, None)
        await callback.answer("Титул снят", show_alert=True)
    await shop_my_callback(callback, state)
