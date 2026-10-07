"""Fetch Telegram profile images server-side without exposing bot file URLs."""
import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

import aiohttp

from config import BOT_TOKEN

log = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_CACHE_BYTES = 16 * 1024 * 1024
_cache = OrderedDict()
_pending = {}


@dataclass(frozen=True)
class Avatar:
    data: bytes
    content_type: str


class AvatarUnavailable(Exception):
    """A temporary Telegram failure; do not cache it as a missing photo."""


def image_content_type(data: bytes) -> str | None:
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _fetch_avatar(user_id: int) -> Avatar | None:
    # getUserProfilePhotos returns PhotoSize images, including static thumbnails
    # for Telegram video avatars. It does not expose the profile video itself.
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with asyncio.timeout(15), aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(base + "/getUserProfilePhotos",
                                   params={"user_id": user_id, "limit": 1}) as response:
                response.raise_for_status()
                photos = await response.json()
            if not photos.get("ok"):
                raise AvatarUnavailable()
            entries = photos["result"]["photos"]
            if not entries:
                return None
            file_id = max(entries[0], key=lambda photo: photo["width"] * photo["height"])["file_id"]
            async with session.get(base + "/getFile", params={"file_id": file_id}) as response:
                response.raise_for_status()
                file = await response.json()
            if not file.get("ok"):
                raise AvatarUnavailable()
            path = file["result"]["file_path"]
            if not isinstance(path, str) or not path or path.startswith("/") or any(
                    part in (".", "..") for part in path.split("/")) or any(
                    char in path for char in ("?", "#", "\\")):
                raise AvatarUnavailable()
            async with session.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}") as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise AvatarUnavailable()
            data = bytes(data)
            content_type = image_content_type(data)
            if not content_type:
                raise AvatarUnavailable()
            return Avatar(data, content_type)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError,
            TypeError, IndexError, AvatarUnavailable) as error:
        # Exception strings from HTTP clients can contain the bot token in a URL.
        log.warning("Avatar download unavailable (%s)", type(error).__name__)
        raise AvatarUnavailable() from None


async def _load_avatar(user_id: int) -> Avatar | None:
    avatar = await _fetch_avatar(user_id)
    _cache[user_id] = (time.monotonic() + (300 if avatar else 60), avatar)
    _cache.move_to_end(user_id)
    while len(_cache) > 128 or sum(len(value.data) for _, value in _cache.values()
                                  if value) > MAX_CACHE_BYTES:
        _cache.popitem(last=False)
    return avatar


async def get_avatar(user_id: int) -> Avatar | None:
    cached = _cache.get(user_id)
    if cached and cached[0] > time.monotonic():
        _cache.move_to_end(user_id)
        return cached[1]
    _cache.pop(user_id, None)
    task = _pending.get(user_id)
    if task is None:
        task = asyncio.create_task(_load_avatar(user_id))
        _pending[user_id] = task

        def completed(done):
            _pending.pop(user_id, None)
            # Retrieve failures even if every HTTP caller disconnected.
            if not done.cancelled():
                done.exception()

        task.add_done_callback(completed)
    return await asyncio.shield(task)
