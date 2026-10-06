"""Bot shortcuts preserve active rounds and enforce device ownership."""
import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from tests.test_webapp_mines import db as global_db  # Configure offline environment.
from database import Database
from handlers import experience
from games.mines import MinesGame
from tests.test_avatars import GIF
from utils.game_registry import registry


class BotExperienceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.db"))
        for uid in (101, 202):
            self.db.register_user(uid, None, "Player")
        self.patches = [patch("handlers.experience.db", self.db),
                        patch("utils.game_registry.db", self.db)]
        for p in self.patches:
            p.start()
        self.state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock())
        self.message = SimpleNamespace(from_user=SimpleNamespace(id=101),
                                       chat=SimpleNamespace(type="private"),
                                       answer=AsyncMock(), edit_text=AsyncMock())
        self.callback = SimpleNamespace(from_user=SimpleNamespace(id=101),
                                        message=self.message, answer=AsyncMock())

    async def asyncTearDown(self):
        registry.release(101)
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def test_resume_returns_same_game_without_a_second_stake(self):
        game = MinesGame(101, 100, 3)
        registry.register(101, "mines", game)
        before = self.db.get_user(101)["balance"]
        await experience.resume_command(self.message, self.state)
        self.assertIs(registry.game(101), game)
        self.assertEqual(self.db.get_user(101)["balance"], before)
        self.message.answer.assert_awaited_once()
        self.assertIsNotNone(self.message.answer.await_args.kwargs["reply_markup"])

    async def test_settings_open_from_an_animated_profile_card(self):
        self.message.animation = object()
        self.message.delete = AsyncMock()
        await experience.settings_callback(self.callback, self.state)
        self.message.edit_text.assert_not_awaited()
        self.message.answer.assert_awaited_once()
        self.assertIn("Ваш профиль и настройки", self.message.answer.await_args.args[0])
        self.message.delete.assert_awaited_once()

    async def test_explicit_favorite_callback_is_idempotent_and_owned(self):
        self.callback.data = "favorite_set:mines:1"
        await experience.favorites_callback(self.callback, self.state)
        await experience.favorites_callback(self.callback, self.state)
        self.assertEqual(self.db.get_player_preferences(101)["favorites"], ["mines"])
        self.assertEqual(self.db.get_player_preferences(202)["favorites"], [])
        self.callback.data = "favorite_set:evil:1"
        await experience.favorites_callback(self.callback, self.state)
        self.assertEqual(self.db.get_player_preferences(101)["favorites"], ["mines"])

    async def test_device_callback_cannot_revoke_another_players_session(self):
        own = self.db.create_mobile_session(101, "Mine", int(time.time()) + 86400)
        other = self.db.create_mobile_session(202, "Other", int(time.time()) + 86400)
        self.callback.data = "device_revoke:" + other
        await experience.devices_callback(self.callback)
        self.assertEqual(len(self.db.list_mobile_sessions(202)), 1)
        self.callback.data = "device_revoke:" + own
        await experience.devices_callback(self.callback)
        self.assertEqual(self.db.list_mobile_sessions(101), [])
        self.assertEqual(len(self.db.list_mobile_sessions(202)), 1)

    async def test_private_gif_upload_preserves_animation_bytes(self):
        self.message.document = SimpleNamespace(file_size=len(GIF))
        self.message.photo = []
        async def download(media, destination):
            destination.write(GIF)
        self.message.bot = SimpleNamespace(download=AsyncMock(side_effect=download))
        await experience.receive_avatar(self.message, self.state)
        self.assertEqual(self.db.get_custom_avatar(101)["data"], GIF)
        self.assertIsNone(self.db.get_custom_avatar(202))
        self.state.clear.assert_awaited_once()

    async def test_invalid_avatar_does_not_replace_existing_photo(self):
        self.db.set_custom_avatar(101, GIF, "image/gif")
        self.message.document = SimpleNamespace(file_size=12)
        self.message.photo = []
        async def download(media, destination):
            destination.write(b"GIF89a-bad")
        self.message.bot = SimpleNamespace(download=AsyncMock(side_effect=download))
        await experience.receive_avatar(self.message, self.state)
        self.assertEqual(self.db.get_custom_avatar(101)["data"], GIF)
        self.state.clear.assert_not_awaited()
