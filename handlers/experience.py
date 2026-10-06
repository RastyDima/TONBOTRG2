"""Player settings and shortcuts shared with the WebApp."""
import asyncio
import html
import io
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import db
from keyboards.common import back_button
from utils.avatar_uploads import validate_avatar
from utils.avatars import MAX_IMAGE_BYTES
from utils.game_registry import registry, set_pending_bet
from utils.helpers import format_number
from utils.player_data import GAMES
from utils.player_views import history_csv

router = Router()


class ProfileSettings(StatesGroup):
    avatar = State()
    bio = State()
    bet = State()


def settings_kb(user_id):
    prefs = db.get_player_preferences(user_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="🖼 Загрузить фото / GIF", callback_data="profile_avatar_upload")
    if prefs["custom_avatar"]:
        kb.button(text="↩ Вернуть фото Telegram", callback_data="profile_avatar_reset")
    kb.button(text="✏️ Описание профиля", callback_data="profile_bio")
    kb.button(text="🎯 Сохранённая ставка", callback_data="profile_bet")
    kb.button(text="🔒 Скрыть в рейтинге" if not prefs["hide_stats"] else "🏆 Показывать в рейтинге",
              callback_data=f"profile_privacy:{int(not prefs['hide_stats'])}")
    kb.button(text="⭐ Избранные игры", callback_data="favorites")
    kb.button(text="📱 Устройства Android", callback_data="devices")
    kb.button(text="🔔 Напоминания", callback_data="reminders")
    kb.adjust(1)
    kb.row(back_button("menu"))
    return kb.as_markup()


def settings_text(user_id):
    prefs = db.get_player_preferences(user_id)
    return ("⚙️ <b>Ваш профиль и настройки</b>\n\n"
            f"Описание: {html.escape(prefs['bio']) or 'не задано'}\n"
            f"Сохранённая ставка: <b>{format_number(prefs['saved_bet'])} TON</b>\n"
            f"Рейтинг: {'скрыт' if prefs['hide_stats'] else 'виден другим игрокам'}\n\n"
            "Фото, GIF, описание, избранное и ставка синхронизируются с приложением.")


@router.message(Command("settings"))
async def settings_command(message: Message, state: FSMContext):
    await state.clear()
    if not db.get_user(message.from_user.id):
        await message.answer("Сначала нажмите /start")
        return
    await message.answer(settings_text(message.from_user.id), reply_markup=settings_kb(message.from_user.id))


@router.callback_query(F.data == "settings", StateFilter("*"))
async def settings_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    if not db.get_user(callback.from_user.id):
        return
    await callback.message.edit_text(settings_text(callback.from_user.id), reply_markup=settings_kb(callback.from_user.id))


@router.message(Command("avatar", "bio", "bet"))
async def setting_command(message: Message, state: FSMContext):
    if not db.get_user(message.from_user.id):
        await message.answer("Сначала нажмите /start")
        return
    if message.chat.type != "private":
        await message.answer("Меняйте профиль в личном чате с ботом.")
        return
    kind = message.text.split()[0].split("@")[0][1:]
    await state.set_state(getattr(ProfileSettings, kind))
    prompts = {"avatar": "Отправьте фото или GIF как файл, до 2 МиБ. GIF, отправленный как видео, Telegram преобразует в MP4. /cancel — отменить.",
               "bio": "Напишите описание до 200 символов. Отправьте «-», чтобы очистить. /cancel — отменить.",
               "bet": "Введите сохранённую ставку в TON. Она появится в приложении и быстрых командах. /cancel — отменить."}
    await message.answer(prompts[kind])


@router.callback_query(F.data.in_({"profile_avatar_upload", "profile_bio", "profile_bet"}), StateFilter("*"))
async def setting_prompt(callback: CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id):
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    await callback.answer()
    if callback.message.chat.type != "private":
        await callback.message.answer("Меняйте профиль в личном чате с ботом: /settings")
        return
    kind = {"profile_avatar_upload": "avatar", "profile_bio": "bio", "profile_bet": "bet"}[callback.data]
    await state.set_state(getattr(ProfileSettings, kind))
    text = {"avatar": "🖼 Отправьте фото или GIF как файл, до 2 МиБ. Для GIF выберите отправку без сжатия. /cancel — отменить.",
            "bio": "✏️ Напишите описание до 200 символов. «-» очистит его. /cancel — отменить.",
            "bet": "🎯 Введите сохранённую ставку в TON. /cancel — отменить."}[kind]
    await callback.message.answer(text)


@router.message(ProfileSettings.avatar, ~F.text.startswith("/"))
async def receive_avatar(message: Message, state: FSMContext):
    media = message.document or (message.photo[-1] if message.photo else None)
    if not media or not media.file_size or media.file_size > MAX_IMAGE_BYTES:
        await message.answer("Нужно фото или GIF-файл до 2 МиБ. Анимацию отправьте как файл без сжатия.")
        return
    buffer = io.BytesIO()
    try:
        await message.bot.download(media, destination=buffer)
        data = buffer.getvalue()
        content_type = await asyncio.to_thread(validate_avatar, data)
    except ValueError:
        await message.answer("Не удалось прочитать изображение. Поддерживаются JPEG, PNG, GIF и WebP.")
        return
    except Exception:
        await message.answer("Не удалось загрузить файл. Попробуйте ещё раз.")
        return
    db.set_custom_avatar(message.from_user.id, data, content_type)
    await state.clear()
    await message.answer("✅ Аватар сохранён для бота, веба и приложения.", reply_markup=settings_kb(message.from_user.id))


@router.message(ProfileSettings.bio, F.text, ~F.text.startswith("/"))
async def receive_bio(message: Message, state: FSMContext):
    value = "" if message.text.strip() == "-" else message.text.strip()
    try:
        db.set_player_preferences(message.from_user.id, {"bio": value})
    except ValueError:
        await message.answer("Описание должно быть не длиннее 200 символов.")
        return
    await state.clear()
    await message.answer("✅ Описание сохранено.", reply_markup=settings_kb(message.from_user.id))


@router.message(ProfileSettings.bet, F.text, ~F.text.startswith("/"))
async def receive_bet(message: Message, state: FSMContext):
    try:
        value = int(message.text.replace(" ", ""))
        db.set_player_preferences(message.from_user.id, {"saved_bet": value})
    except ValueError:
        from config import MAX_BET
        await message.answer(f"Введите целую ставку от 1 до {format_number(MAX_BET)} TON.")
        return
    await state.clear()
    await message.answer("✅ Ставка сохранена.", reply_markup=settings_kb(message.from_user.id))


@router.callback_query(F.data.startswith("profile_privacy:"), StateFilter("*"))
async def privacy(callback: CallbackQuery):
    if not db.get_user(callback.from_user.id):
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    if callback.data not in ("profile_privacy:0", "profile_privacy:1"):
        await callback.answer("Неизвестная настройка", show_alert=True)
        return
    db.set_player_preferences(callback.from_user.id, {"hide_stats": callback.data.endswith(":1")})
    await callback.answer("Настройки сохранены")
    await callback.message.edit_text(settings_text(callback.from_user.id), reply_markup=settings_kb(callback.from_user.id))


@router.callback_query(F.data == "profile_avatar_reset", StateFilter("*"))
async def avatar_reset(callback: CallbackQuery):
    db.delete_custom_avatar(callback.from_user.id)
    await callback.answer("Теперь используется фото Telegram")
    await callback.message.edit_text(settings_text(callback.from_user.id), reply_markup=settings_kb(callback.from_user.id))


def favorites_screen(user_id):
    prefs = db.get_player_preferences(user_id)
    kb = InlineKeyboardBuilder()
    for game_id in prefs["favorites"]:
        game = GAMES[game_id]
        kb.button(text=f"{game['icon']} {game['name']}", callback_data=f"favorite_play:{game_id}")
    kb.adjust(2)
    for game_id, game in GAMES.items():
        enabled = game_id in prefs["favorites"]
        kb.button(text=f"{'✅' if enabled else '☆'} {game['name']}", callback_data=f"favorite_set:{game_id}:{int(not enabled)}")
    kb.adjust(2)
    kb.row(back_button("menu"))
    examples = "\n".join(f"<code>{GAMES[game_id]['command']} {prefs['saved_bet']}</code>" for game_id in prefs["favorites"] if GAMES[game_id]["command"])
    return ("⭐ <b>Избранные игры</b>\n\nОткрывайте игру верхней кнопкой. Добавляйте её кнопкой ☆.\n"
            f"Сохранённая ставка: {format_number(prefs['saved_bet'])} TON.\n\n{examples}", kb.as_markup())


@router.message(Command("favorites"))
async def favorites_command(message: Message):
    if db.get_user(message.from_user.id):
        text, markup = favorites_screen(message.from_user.id)
        await message.answer(text, reply_markup=markup)


@router.callback_query((F.data == "favorites") | F.data.startswith("favorite_set:"), StateFilter("*"))
async def favorites_callback(callback: CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id):
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    await state.clear()
    if callback.data.startswith("favorite_set:"):
        parts = callback.data.split(":")
        if len(parts) != 3 or parts[1] not in GAMES or parts[2] not in ("0", "1"):
            await callback.answer("Неизвестная игра", show_alert=True)
            return
        db.set_favorite(callback.from_user.id, parts[1], parts[2] == "1")
    await callback.answer()
    text, markup = favorites_screen(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data.startswith("favorite_play:"), StateFilter("*"))
async def favorite_play(callback: CallbackQuery, state: FSMContext):
    from handlers import alchemist, blackjack, coinflip, joker, mines, ruby_roulette
    kind = callback.data.split(":", 1)[1]
    if kind not in GAMES or not db.get_user(callback.from_user.id):
        await callback.answer("Неизвестная игра", show_alert=True)
        return
    await state.clear()
    if kind in ("mines", "joker", "alchemist") and not registry.is_active(callback.from_user.id):
        set_pending_bet(callback.from_user.id, db.get_player_preferences(callback.from_user.id)["saved_bet"])
    if kind == "mines":
        await mines.mines_count_menu(callback)
    elif kind == "joker":
        await joker.joker_level_menu(callback)
    elif kind == "alchemist":
        await alchemist.alchemist_menu(callback)
    elif kind == "coinflip":
        await coinflip.coinflip_menu(callback, state)
    elif kind == "blackjack":
        await blackjack.blackjack_menu(callback, state)
    else:
        await ruby_roulette.ruby_roulette_menu(callback, state)


def active_screen(user_id):
    entry = registry.get(user_id)
    if not entry:
        return "Сейчас нет незавершённой игры.", None
    game, kind = entry["game"], entry["type"]
    from handlers import alchemist, blackjack, coinflip, joker, mines, ruby_roulette
    if kind == "mines":
        return mines.field_text(game), mines.field_kb(game)
    if kind == "joker":
        return joker.field_text(game), joker.field_kb(game)
    if kind == "blackjack":
        return blackjack.round_text(game), blackjack.round_kb(game)
    if kind == "alchemist":
        return (alchemist.brew_text(game), alchemist.brew_kb()) if len(game.picks) == 2 else (alchemist.pick_text(game, True), alchemist.ingredients_kb(game))
    if kind == "coinflip":
        return f"🪙 Монетка · ставка {format_number(game.bet)} TON. Выберите сторону:", coinflip.choice_kb()
    return f"🎰 Рулетка · ставка {game.bet} 💎. Выберите сектор:", ruby_roulette.choice_kb()


@router.message(Command("resume"))
async def resume_command(message: Message, state: FSMContext):
    await state.clear()
    text, markup = active_screen(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "resume", StateFilter("*"))
async def resume_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    text, markup = active_screen(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup)


def devices_screen(user_id):
    sessions = db.list_mobile_sessions(user_id)
    kb = InlineKeyboardBuilder()
    lines = ["📱 <b>Подключённые Android-устройства</b>"]
    for session in sessions:
        seen = datetime.fromtimestamp(session["last_seen_at"]).strftime("%d.%m %H:%M")
        lines.append(f"\n{html.escape(session['device_label'])} · {seen}")
        kb.button(text="Отключить " + session["device_label"][:35], callback_data="device_revoke:" + session["id"])
    if sessions:
        kb.button(text="Отключить все Android-устройства", callback_data="devices_revoke_all")
    else:
        lines.append("\nУстройств пока нет. Подключите приложение через одноразовый код.")
    kb.adjust(1)
    kb.row(back_button("settings"))
    return "\n".join(lines), kb.as_markup()


@router.message(Command("devices"))
async def devices_command(message: Message):
    if message.chat.type != "private":
        await message.answer("Управляйте устройствами в личном чате: /devices")
        return
    text, markup = devices_screen(message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.callback_query((F.data == "devices") | F.data.startswith("device_revoke:") | (F.data == "devices_revoke_all"), StateFilter("*"))
async def devices_callback(callback: CallbackQuery):
    if callback.message.chat.type != "private":
        await callback.answer("Откройте личный чат с ботом", show_alert=True)
        return
    if callback.data.startswith("device_revoke:"):
        db.revoke_mobile_session(callback.from_user.id, callback.data.split(":", 1)[1])
    elif callback.data == "devices_revoke_all":
        db.revoke_other_mobile_sessions(callback.from_user.id, None)
    await callback.answer()
    text, markup = devices_screen(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=markup)


@router.message(Command("stats"))
async def stats_command(message: Message):
    if not db.get_user(message.from_user.id):
        return
    data = db.player_statistics(message.from_user.id, 30)["summary"]
    await message.answer("📈 <b>Статистика за 30 дней</b>\n\n"
                         f"Игр: {data['games']} · побед: {data['wins']}\n"
                         f"Доля побед: {data['winrate']}%\n"
                         f"Ставки: {format_number(data['bets'])} TON\n"
                         f"Выплаты: {format_number(data['payouts'])} TON\n"
                         f"Результат: {data['net']:+} TON\n\n"
                         "График баланса и результаты по играм доступны в приложении.")


@router.message(Command("history_export"))
async def history_export_command(message: Message):
    if message.chat.type != "private":
        await message.answer("Получите CSV в личном чате: /history_export")
        return
    if not db.get_user(message.from_user.id):
        await message.answer("Сначала нажмите /start")
        return
    await message.answer_document(BufferedInputFile(history_csv(db, message.from_user.id), filename="ton-history.csv"),
                                  caption="До 1000 последних операций вашего аккаунта.")
