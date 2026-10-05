"""Avatar download, cache and Telegram media delivery regressions."""
import asyncio
import base64
import importlib.util
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "offline-avatar-tests")
os.environ.setdefault("RENDER", "false")
os.environ.setdefault("ADMIN_PANEL_PASSWORD", "offline-avatar-tests")
os.environ.setdefault("WEBHOOK_SECRET", "offline-avatar-tests")

from PIL import Image
from utils import avatars

GIF = base64.b64decode("R0lGODlhEAAQAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQADAAAACwAAAAAEAAQAAAIHQABCBxIsKDBgwgTKlzIsKHDhxAjSpxIsaLFgQEBACH5BAEMAAEALAAAAAAQABAAgQAA/wAAAAAAAAAAAAgdAAEIHEiwoMGDCBMqXMiwocOHECNKnEixosWBAQEAOw==")


class Response:
    def __init__(self, payload=None, body=b""):
        self.payload, self.body = payload, body
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def json(self):
        return self.payload

    async def iter_chunked(self, size):
        for offset in range(0, len(self.body), size):
            yield self.body[offset:offset + size]


class Session(Response):
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


class AvatarTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        avatars._cache.clear()
        self.assertFalse(avatars._pending)

    def session(self, data=GIF):
        return Session([
            Response({"ok": True, "result": {"photos": [[
                {"file_id": "small", "width": 20, "height": 20},
                {"file_id": "large", "width": 640, "height": 640},
            ]]}}),
            Response({"ok": True, "result": {"file_path": "photos/test.gif"}}),
            Response(body=data),
        ])

    async def test_download_preserves_gif_and_chooses_largest_photo(self):
        session = self.session()
        with patch.object(avatars.aiohttp, "ClientSession", return_value=session):
            result = await avatars._fetch_avatar(101)
        self.assertEqual(result.data, GIF)
        self.assertEqual(result.content_type, "image/gif")
        self.assertEqual(Image.open(io.BytesIO(result.data)).n_frames, 2)
        self.assertEqual(session.requests[0][1]["params"]["user_id"], 101)
        self.assertEqual(session.requests[1][1]["params"]["file_id"], "large")

    async def test_missing_photo_stops_before_get_file(self):
        session = Session([Response({"ok": True, "result": {"photos": []}})])
        with patch.object(avatars.aiohttp, "ClientSession", return_value=session):
            self.assertIsNone(await avatars._fetch_avatar(101))
        self.assertEqual(len(session.requests), 1)

    async def test_unsupported_and_oversized_images_are_rejected(self):
        for data in (b"<svg>untrusted</svg>", b"GIF89a" + b"0" * avatars.MAX_IMAGE_BYTES):
            with patch.object(avatars.aiohttp, "ClientSession", return_value=self.session(data)):
                with self.assertRaises(avatars.AvatarUnavailable):
                    await avatars._fetch_avatar(101)

    async def test_error_logs_do_not_include_file_urls_or_token(self):
        with patch.object(avatars.aiohttp, "ClientSession",
                          side_effect=ValueError("https://api.telegram.org/bot" + avatars.BOT_TOKEN)):
            with self.assertLogs(avatars.log, level="WARNING") as logs:
                with self.assertRaises(avatars.AvatarUnavailable):
                    await avatars._fetch_avatar(101)
        self.assertNotIn(avatars.BOT_TOKEN, " ".join(logs.output))
        self.assertNotIn("https://", " ".join(logs.output))

    async def test_cache_and_inflight_requests_are_scoped_to_user(self):
        async def fetch(user_id):
            await asyncio.sleep(0)
            return avatars.Avatar(str(user_id).encode(), "image/jpeg")
        with patch.object(avatars, "_fetch_avatar", side_effect=fetch) as fetcher:
            first, same, other = await asyncio.gather(
                avatars.get_avatar(101), avatars.get_avatar(101), avatars.get_avatar(202))
            self.assertEqual(first, same)
            self.assertNotEqual(first, other)
            self.assertEqual(await avatars.get_avatar(101), first)
            self.assertEqual(fetcher.await_count, 2)

    async def test_temporary_error_is_retried_instead_of_cached(self):
        expected = avatars.Avatar(GIF, "image/gif")
        with patch.object(avatars, "_fetch_avatar",
                          side_effect=[avatars.AvatarUnavailable(), expected]) as fetcher:
            with self.assertRaises(avatars.AvatarUnavailable):
                await avatars.get_avatar(101)
            self.assertEqual(await avatars.get_avatar(101), expected)
        self.assertEqual(fetcher.await_count, 2)

    async def test_disconnected_caller_does_not_cancel_shared_download(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def fetch(user_id):
            started.set()
            await finish.wait()
            return avatars.Avatar(GIF, "image/gif")
        with patch.object(avatars, "_fetch_avatar", side_effect=fetch) as fetcher:
            caller = asyncio.create_task(avatars.get_avatar(101))
            await started.wait()
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            finish.set()
            self.assertEqual((await avatars.get_avatar(101)).data, GIF)
        self.assertEqual(fetcher.await_count, 1)

    async def test_cache_expires_and_stays_within_memory_budget(self):
        result = avatars.Avatar(GIF, "image/gif")
        with patch.object(avatars, "_fetch_avatar", return_value=result) as fetcher:
            await avatars.get_avatar(101)
            avatars._cache[101] = (0, result)
            await avatars.get_avatar(101)
            self.assertEqual(fetcher.await_count, 2)
            with patch.object(avatars, "MAX_CACHE_BYTES", len(GIF)):
                await avatars.get_avatar(202)
            self.assertEqual(list(avatars._cache), [202])


@unittest.skipUnless(importlib.util.find_spec("aiogram"), "aiogram is not installed")
class ProfileMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_and_callback_send_gif_as_animation(self):
        from handlers import profile
        fake_db = SimpleNamespace(get_user=lambda _: {"id": 101}, get_stats=lambda _: {})
        for callback_mode in (False, True):
            message = SimpleNamespace(from_user=SimpleNamespace(id=101),
                                      answer_photo=AsyncMock(), answer_animation=AsyncMock(),
                                      delete=AsyncMock())
            with patch.object(profile, "db", fake_db), patch.object(
                    profile, "_make_card", return_value=("profile.gif", GIF)):
                if callback_mode:
                    callback = SimpleNamespace(message=message, from_user=message.from_user,
                                               answer=AsyncMock())
                    await profile.profile_callback(callback, SimpleNamespace(clear=AsyncMock()))
                else:
                    await profile.profile_command(message)
            message.answer_photo.assert_not_awaited()
            self.assertEqual(message.answer_animation.await_args.kwargs["animation"].data, GIF)

    async def test_simultaneous_cards_keep_their_own_bytes(self):
        from handlers.profile import _send_profile_card
        messages = [SimpleNamespace(answer_photo=AsyncMock(), answer_animation=AsyncMock())
                    for _ in range(2)]
        await asyncio.gather(*(_send_profile_card(message, "profile.png", data)
                               for message, data in zip(messages, (b"first", b"second"))))
        self.assertEqual(messages[0].answer_photo.await_args.kwargs["photo"].data, b"first")
        self.assertEqual(messages[1].answer_photo.await_args.kwargs["photo"].data, b"second")
