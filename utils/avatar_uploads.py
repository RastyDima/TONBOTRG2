"""Validate uploaded images while preserving GIF animation."""
import io
import warnings

from PIL import Image, UnidentifiedImageError
from utils.avatars import MAX_IMAGE_BYTES, image_content_type


def validate_avatar(data: bytes) -> str:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("avatar must be under 2 MiB")
    content_type = image_content_type(data)
    if not content_type:
        raise ValueError("unsupported avatar format")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                expected = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}.get(source.format)
                count = getattr(source, "n_frames", 1)
                if expected != content_type or count > 120 or source.width * source.height > 4_000_000 or source.width * source.height * count > 40_000_000:
                    raise ValueError("avatar dimensions or animation exceed limits")
                for index in range(count):
                    source.seek(index)
                    source.load()
    except (OSError, EOFError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise ValueError("invalid avatar image") from None
    return content_type
