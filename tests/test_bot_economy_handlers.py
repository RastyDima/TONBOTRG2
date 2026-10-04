"""Exercise bot callbacks with real keyboards and an isolated balance ledger."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

_scratch = tempfile.TemporaryDirectory()
os.environ.update({
    "BOT_TOKEN": "offline-economy-tests", "RENDER": "false", "DATABASE_URL": "",
    "DATABASE_PATH": str(Path(_scratch.name) / "global.db"),
    "ADMIN_PANEL_PASSWORD": "offline-economy-tests", "WEBHOOK_SECRET": "offline-economy-tests",
})


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class EconomyHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from database import Database
        from handlers import economy
        from utils import achievements, game_registry, helpers
        self.economy = economy
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database(str(Path(self.temp.name) / "test.db"))
        self.db.register_user(101, None, "Player")
        for module in (economy, achievements, game_registry, helpers):
            replacement = patch.object(module, "db", self.db)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.state = SimpleNamespace(clear=AsyncMock())

    def callback(self, data):
        return SimpleNamespace(
            data=data, from_user=SimpleNamespace(id=101), answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock()),
        )

    async def test_bonus_menu_does_not_claim_until_a_bonus_is_selected(self):
        callback = self.callback("bonuses")
        before = self.db.get_user(101)["balance"]
        await self.economy.bonuses_callback(callback, self.state)
        self.assertEqual(self.db.get_user(101)["balance"], before)
        text = callback.message.edit_text.await_args.args[0]
        self.assertIn("Ежедневный", text)
        self.assertIn("Еженедельный", text)
        markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "daily")
        self.assertEqual(markup.inline_keyboard[1][0].callback_data, "weekly")

    async def test_old_claim_buttons_credit_and_award_xp_once(self):
        for kind, xp in (("daily", 15), ("weekly", 50)):
            callback = self.callback(kind)
            before = self.db.get_user(101)["xp"]
            await self.economy.bonuses_callback(callback, self.state)
            self.assertEqual(self.db.get_user(101)["xp"], before + xp)
            balance = self.db.get_user(101)["balance"]
            await self.economy.bonuses_callback(callback, self.state)
            self.assertEqual(self.db.get_user(101)["xp"], before + xp)
            self.assertEqual(self.db.get_user(101)["balance"], balance)

    async def test_commands_with_bot_suffix_preserve_claim_behavior(self):
        message = SimpleNamespace(text="/daily@tonbotgram_bot", from_user=SimpleNamespace(id=101), answer=AsyncMock())
        await self.economy.bonuses_command(message, self.state)
        self.assertIsNotNone(self.db.get_user(101)["last_daily"])
        self.assertIn("Еженедельный", message.answer.await_args.args[0])

    async def test_stale_reminder_button_sets_an_explicit_value(self):
        callback = self.callback("reminder:daily:0")
        await self.economy.reminder_toggle(callback, self.state)
        await self.economy.reminder_toggle(callback, self.state)
        self.assertEqual(self.db.get_user(101)["daily_reminder_enabled"], 0)
        self.assertEqual(self.db.get_user(101)["weekly_reminder_enabled"], 1)

    async def test_invalid_reminder_button_cannot_update_other_columns(self):
        callback = self.callback("reminder:is_admin:1")
        await self.economy.reminder_toggle(callback, self.state)
        self.assertEqual(self.db.get_user(101)["is_admin"], 0)
        callback.message.edit_text.assert_not_awaited()

    async def test_history_page_and_filter_buttons_keep_the_snapshot(self):
        for number in range(14):
            self.db.add_balance(101, 1, "shop", str(number))
        anchor = self.db.get_transactions(101, 1)[0]["id"]
        callback = self.callback(f"history:shop:1:{anchor}")
        await self.economy.history_callback(callback, self.state)
        self.assertIn("Страница 2/2", callback.message.edit_text.await_args.args[0])
        markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
        self.assertTrue(all(len(button.callback_data.encode()) <= 64
                            for row in markup.inline_keyboard for button in row))
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, f"history:all:0:{anchor}")

    async def test_malformed_history_buttons_show_an_alert(self):
        for data in ("history:all:bad:1", "history:shop:-1:1", "history_refresh:invalid"):
            callback = self.callback(data)
            await self.economy.history_callback(callback, self.state)
            self.assertTrue(callback.answer.await_args.kwargs["show_alert"])
            callback.message.edit_text.assert_not_awaited()

    async def test_repeated_screen_edit_ignores_only_not_modified_errors(self):
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods import EditMessageText
        callback = self.callback("bonuses")
        callback.message.edit_text.side_effect = TelegramBadRequest(
            method=EditMessageText(chat_id=101, message_id=1, text="menu"),
            message="Bad Request: message is not modified",
        )
        await self.economy.bonuses_callback(callback, self.state)
        callback.message.edit_text.side_effect = TelegramBadRequest(
            method=EditMessageText(chat_id=101, message_id=1, text="menu"),
            message="Bad Request: chat not found",
        )
        with self.assertRaises(TelegramBadRequest):
            await self.economy.bonuses_callback(callback, self.state)


if __name__ == "__main__":
    unittest.main()
