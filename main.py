import asyncio
import logging

from aiohttp import ClientSession, web
from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

from config import BOT_TOKEN, PORT, PUBLIC_BASE_URL, WEBHOOK_PATH, WEBHOOK_SECRET, WEBHOOK_URL
from database import db
from handlers import register_handlers
from utils import notify
from utils.reminders import send_bonus_reminders
from utils.helpers import get_daily_bonus, get_weekly_bonus
from webadmin import register_admin_routes
from webapp_routes import register_webapp_routes

logging.basicConfig(level=logging.INFO)

APP_VERSION = "ceae6f4+allowed-updates"
logging.info("Starting TONBOTRG build %s (WEBHOOK=%s, backend=%s)", APP_VERSION, bool(WEBHOOK_URL), type(db).__name__)

REMINDER_INTERVAL = 30 * 60  # секунд
HEARTBEAT_INTERVAL = 4 * 60  # секунд, меньше порога простоя Render (~15 мин)


def _bonus_kb(action: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Забрать бонус", callback_data=action)
    kb.button(text="🔔 Настройки напоминаний", callback_data="reminders")
    kb.adjust(1)
    return kb.as_markup()


async def reminder_loop() -> None:
    """Раз в полчаса напоминает игрокам о доступных бонусах (ежедневный/еженедельный)."""
    logging.info("Reminder loop started")
    while True:
        try:
            await send_bonus_reminders(
                db, notify.send, get_daily_bonus(), get_weekly_bonus(), _bonus_kb,
            )
        except Exception:  # noqa: BLE001
            logging.exception("reminder loop error")
        await asyncio.sleep(REMINDER_INTERVAL)


def start_reminder_loop() -> asyncio.Task:
    return asyncio.create_task(reminder_loop())


async def heartbeat_loop() -> None:
    """Каждые 4 минуты пингует собственный /health через публичный URL.

    Создаёт постоянный входящий трафик, поэтому бесплатный Render не усыпляет
    инстанс (порог простоя — 15 минут без запросов).
    """
    if not PUBLIC_BASE_URL:
        return
    url = PUBLIC_BASE_URL.rstrip("/") + "/health"
    logging.info("Heartbeat: keeping %s awake (every %ds)", url, HEARTBEAT_INTERVAL)
    while True:
        try:
            async with ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status != 200:
                        logging.warning("Heartbeat: status %s", resp.status)
        except Exception:  # noqa: BLE001
            logging.warning("Heartbeat: ping to %s failed", url, exc_info=True)
        await asyncio.sleep(HEARTBEAT_INTERVAL)


def start_heartbeat() -> asyncio.Task:
    return asyncio.create_task(heartbeat_loop())


WEBHOOK_CHECK_INTERVAL = 5 * 60  # каждые 5 минут


async def webhook_guard_loop(bot: Bot) -> None:
    """Каждые 5 минут проверяет, что вебхук не был перехвачен."""
    expected_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
    logging.info("Webhook guard: watching for %s (every %ds)", expected_url, WEBHOOK_CHECK_INTERVAL)
    while True:
        try:
            await asyncio.sleep(WEBHOOK_CHECK_INTERVAL)
            info = await bot.get_webhook_info()
            current = info.url
            if current and current != expected_url:
                logging.critical("WEBHOOK HIJACKED! Current=%s, expected=%s — restoring!", current, expected_url)
                await bot.set_webhook(
                    expected_url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True,
                    allowed_updates=["message", "callback_query", "inline_query"],
                )
                logging.critical("Webhook restored to %s", expected_url)
            elif not current:
                logging.warning("Webhook empty — re-setting to %s", expected_url)
                await bot.set_webhook(
                    expected_url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True,
                    allowed_updates=["message", "callback_query", "inline_query"],
                )
        except Exception:
            logging.exception("webhook guard error")


class BlockedUserMiddleware(BaseMiddleware):
    """Перехватывает все апдейты от заблокированных пользователей."""

    async def __call__(self, handler, event, data):
        try:
            inner = event.event if isinstance(event, Update) else event
            utype = type(inner).__name__
            user = getattr(inner, "from_user", None)
            uid = user.id if user else "?"
            if isinstance(inner, CallbackQuery):
                logging.info("CB query: data=%s user=%s", inner.data, uid)
            elif isinstance(inner, Message):
                logging.info("MSG: text=%s user=%s", inner.text[:50] if inner.text else "?", uid)
            else:
                logging.info("UPDATE type=%s user=%s", utype, uid)
            if user is not None and db.is_user_blocked(user.id):
                if isinstance(inner, Message):
                    await inner.answer("🚫 Вы заблокированы. Обратитесь к администратору.")
                elif isinstance(inner, CallbackQuery):
                    await inner.answer("🚫 Вы заблокированы.", show_alert=True)
                return
            return await handler(event, data)
        except Exception:
            logging.exception("BlockedUserMiddleware error for %s", type(event).__name__)
            return await handler(event, data)


def build_app() -> web.Application:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(BlockedUserMiddleware())
    register_handlers(dp)

    async def on_startup(*args, **kwargs) -> None:
        webhook_url = WEBHOOK_URL + WEBHOOK_PATH
        await bot.set_webhook(
            webhook_url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "inline_query"],
        )
        info = await bot.get_webhook_info()
        logging.info(
            "Webhook set: url=%s pending=%s last_error=%s allowed=%s",
            info.url, info.pending_update_count,
            info.last_error_message, info.allowed_updates,
        )

    async def on_shutdown(*args, **kwargs) -> None:
        logging.info("Bot shutdown (webhook left intact)")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)

    async def start_background(app) -> None:
        notify.set_bot(bot)
        await dp.emit_startup()
        app["reminder_task"] = start_reminder_loop()
        app["heartbeat_task"] = start_heartbeat()
        app["webhook_guard_task"] = asyncio.create_task(webhook_guard_loop(bot))

    async def stop_background(app) -> None:
        for key in ("reminder_task", "heartbeat_task", "webhook_guard_task"):
            task = app.get(key)
            if task:
                task.cancel()
        await dp.emit_shutdown()

    app.on_startup.append(start_background)
    app.on_cleanup.append(stop_background)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    register_admin_routes(app)
    register_webapp_routes(app)
    return app

    return app


async def main() -> None:
    db.init_db()
    logging.info("Database backend: %s", type(db).__name__)
    if WEBHOOK_URL:
        app = build_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
        await site.start()
        logging.info("Webhook server running on port %d", PORT)
        await asyncio.Event().wait()
    else:
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher(storage=MemoryStorage())
        dp.update.middleware(BlockedUserMiddleware())
        register_handlers(dp)
        notify.set_bot(bot)
        reminder_task = start_reminder_loop()
        heartbeat_task = start_heartbeat()
        guard_task = asyncio.create_task(webhook_guard_loop(bot))

        # Открываем порт для Render (health check), чтобы деплой считался живым,
        # а старый инстанс не конфликтовал с новым.
        app = web.Application()

        async def health(request):
            return web.Response(text="OK")

        app.router.add_get("/health", health)
        register_admin_routes(app)
        register_webapp_routes(app)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
        await site.start()
        logging.info("Health server running on port %d", PORT)

        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
        finally:
            reminder_task.cancel()
            heartbeat_task.cancel()
            guard_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
