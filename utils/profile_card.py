"""Compact profile cards with custom frames, mixed-script names and animated avatars."""

import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps
from utils.helpers import format_number

SCALE = 2
W, H = 600 * SCALE, 780 * SCALE
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
WHITE = (242, 241, 250)
MUTED = (158, 158, 182)
DIM = (113, 116, 143)
PURPLE = (173, 145, 255)
GREEN = (99, 218, 177)
PINK = (247, 139, 182)
BORDER = (46, 47, 66)
PANEL = (26, 28, 43)
FRAME_COLORS = {
    "frame_neon_green": (0, 255, 120), "frame_fire_red": (255, 60, 40),
    "frame_ice_blue": (60, 180, 255), "frame_gold": (255, 210, 60),
    "frame_diamond": (180, 230, 255),
}
TITLE_DISPLAY = {
    "title_vip": ("VIP", (242, 203, 116)),
    "title_legend": ("LEGEND", (255, 183, 109)),
    "title_whale": ("WHALE", (112, 201, 255)),
    "title_god": ("GOD", PURPLE),
    "title_owner": ("OWNER", (255, 142, 151)),
    "title_ket": ("KET", (111, 230, 192)),
}


@lru_cache(maxsize=128)
def _font(size, bold=True, cjk=False):
    filenames = (("noto_cjk.otf", "arial.ttf") if cjk else
                 ("arialbd.ttf" if bold else "arial.ttf", "noto_cjk.otf"))
    for filename in filenames:
        path = os.path.join(FONT_DIR, filename)
        if os.path.exists(path):
            return ImageFont.truetype(path, size * SCALE)
    return ImageFont.load_default()


def _is_cjk(char):
    code = ord(char)
    return (0x2E80 <= code <= 0xA4CF or 0xAC00 <= code <= 0xD7AF
            or 0xF900 <= code <= 0xFAFF or 0xFF00 <= code <= 0xFFEF
            or 0x20000 <= code <= 0x3134F)


def _runs(text, size, bold):
    """Use real Arial weights, falling back only for CJK characters."""
    runs = []
    for char in text:
        cjk = _is_cjk(char)
        if runs and runs[-1][1] == cjk:
            runs[-1] = (runs[-1][0] + char, cjk)
        else:
            runs.append((char, cjk))
    return [(part, _font(size, bold, cjk)) for part, cjk in runs]


def _width(text, size, bold=True):
    return sum(font.getlength(part) for part, font in _runs(text, size, bold)) / SCALE


def _fit(text, size, max_width, bold=True, min_size=None):
    while size > (min_size or size) and _width(text, size, bold) > max_width:
        size -= 1
    if _width(text, size, bold) > max_width:
        while text and _width(text + "…", size, bold) > max_width:
            text = text[:-1]
        text += "…"
    return text, size


def _text(img, xy, text, size, color=WHITE, *, bold=False,
          max_width=None, min_size=None, align="left"):
    text = " ".join(str(text).split())
    if not text:
        return
    if max_width is not None:
        text, size = _fit(text, size, max_width, bold, min_size)
    runs = _runs(text, size, bold)
    width = sum(font.getlength(part) for part, font in runs)
    x, y = xy[0] * SCALE, xy[1] * SCALE
    x -= width if align == "right" else width / 2 if align == "center" else 0
    draw = ImageDraw.Draw(img)
    top = min(draw.textbbox((0, 0), part, font=font, anchor="ls")[1]
              for part, font in runs)
    for part, font in runs:
        draw.text((x, y - top), part, font=font, fill=color, anchor="ls")
        x += font.getlength(part)


def _rect(img, xy, fill=PANEL, radius=16, outline=None):
    ImageDraw.Draw(img).rounded_rectangle(
        tuple(round(v * SCALE) for v in xy), radius=radius * SCALE,
        fill=fill, outline=outline, width=SCALE)


def _line(img, xy, fill=BORDER):
    ImageDraw.Draw(img).line(tuple(v * SCALE for v in xy), fill=fill, width=SCALE)


def _gradient(width, height, start, end):
    strip = Image.new("RGB", (width, 1))
    strip.putdata([tuple(round(a + (b - a) * x / max(width - 1, 1))
                        for a, b in zip(start, end)) for x in range(width)])
    return strip.resize((width, height))


def _round_mask(width, height, radius):
    mask = Image.new("L", (width, height))
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=radius, fill=255)
    return mask


def _gradient_panel(img, xy, start, end, radius=16):
    x0, y0, x1, y1 = (round(v * SCALE) for v in xy)
    width, height = x1 - x0, y1 - y0
    img.paste(_gradient(width, height, start, end), (x0, y0),
              _round_mask(width, height, radius * SCALE))


def _progress(img, xy, progress):
    """Clip to the rounded track without exaggerating tiny progress values."""
    x0, y0, x1, y1 = (round(v * SCALE) for v in xy)
    width, height = x1 - x0, y1 - y0
    track = Image.new("RGB", (width, height), (48, 48, 69))
    fill_width = round(width * max(0, min(progress, 1)))
    if fill_width:
        fill = _gradient(width, height, PURPLE, (127, 112, 236))
        track.paste(fill.crop((0, 0, fill_width, height)), (0, 0))
    img.paste(track, (x0, y0), _round_mask(width, height, height // 2))


def _gem(img, cx, cy, size, color, ton=False):
    draw = ImageDraw.Draw(img)
    if ton:
        points = [(cx - size, cy - size * .65), (cx + size, cy - size * .65), (cx, cy + size)]
        draw.line([(x * SCALE, y * SCALE) for x, y in points + [points[0]]],
                  fill=color, width=2 * SCALE, joint="curve")
        _line(img, (cx, cy - size * .65, cx, cy + size), color)
    else:
        points = [(cx - size * .55, cy - size * .7), (cx + size * .55, cy - size * .7),
                  (cx + size, cy - size * .1), (cx, cy + size), (cx - size, cy - size * .1)]
        draw.polygon([(x * SCALE, y * SCALE) for x, y in points], fill=color)
        _line(img, (cx - size, cy - size * .1, cx + size, cy - size * .1), (255, 196, 217))
        _line(img, (cx - size * .55, cy - size * .7, cx, cy + size), (255, 196, 217))


def _badge(img, xy, label, color):
    label = " ".join(str(label).split())
    label, size = _fit(label, 10, 320, True)
    x, y = xy
    background = tuple(round(c * .14 + b * .86) for c, b in zip(color, PANEL))
    _rect(img, (x, y, x + _width(label, size) + 28, y + 24), background, radius=8)
    ImageDraw.Draw(img).ellipse(((x + 9) * SCALE, (y + 10) * SCALE,
                                (x + 13) * SCALE, (y + 14) * SCALE), fill=color)
    _text(img, (x + 19, y + 7), label, size, color, bold=True)


AVATAR_XY = (50, 89, 138, 177)


def _avatar_frames(data):
    """Sample at most ten frames while retaining the source loop duration."""
    if not data:
        return [], []
    try:
        with Image.open(io.BytesIO(data)) as source:
            count = getattr(source, "n_frames", 1)
            indices = {int(i * count / min(count, 10)) for i in range(min(count, 10))}
            frames, durations = [], []
            for index in range(count):
                source.seek(index)
                if index in indices:
                    avatar = ImageOps.exif_transpose(source.copy()).convert("RGBA")
                    frames.append(ImageOps.fit(
                        avatar, (88 * SCALE, 88 * SCALE), method=Image.Resampling.LANCZOS))
                    durations.append(0)
                durations[-1] += max(20, int(source.info.get("duration", 120) or 120))
            return frames, durations
    except (OSError, ValueError, EOFError):
        return [], []


def _paste_avatar(img, avatar):
    x0, y0, x1, y1 = (v * SCALE for v in AVATAR_XY)
    mask = Image.new("L", (x1 - x0, y1 - y0))
    ImageDraw.Draw(mask).ellipse((0, 0, mask.width - 1, mask.height - 1), fill=255)
    patch = Image.alpha_composite(img.crop((x0, y0, x1, y1)).convert("RGBA"), avatar)
    img.paste(patch.convert("RGB"), (x0, y0), mask)


def generate_profile_card(
    user_id: int, name: str, balance: int, rubies: float,
    total_games: int, wins: int, losses: int, total_bet: int, total_won: int,
    ref_count: int = 0, frame: str | None = None, avatar_bytes: bytes | None = None,
    title: str | None = None, xp: int = 0, ach_count: int = 0, ach_total: int = 0,
) -> io.BytesIO:
    from database import level_info, level_name

    img = Image.new("RGB", (W, H), (12, 14, 23))
    _gradient_panel(img, (16, 16, 584, 764), (25, 25, 43), (17, 21, 32), radius=28)
    _rect(img, (16, 16, 584, 764), fill=None, radius=28, outline=BORDER)
    _gem(img, 49, 47, 8, PURPLE, ton=True)
    _text(img, (66, 40), "TON", 14, WHITE, bold=True)
    _text(img, (560, 43), "ПРОФИЛЬ ИГРОКА", 10, MUTED, align="right")
    _line(img, (40, 69, 560, 69))

    ring_color = FRAME_COLORS.get(frame, PURPLE)
    draw = ImageDraw.Draw(img)
    draw.ellipse((45 * SCALE, 84 * SCALE, 143 * SCALE, 182 * SCALE),
                 outline=ring_color, width=2 * SCALE)
    draw.ellipse(tuple(v * SCALE for v in AVATAR_XY), fill=(40, 37, 64))
    clean_name = " ".join((name or "Игрок").split()) or "Игрок"
    frames, durations = _avatar_frames(avatar_bytes)
    if not frames:
        _text(img, (94, 116), clean_name[:1].upper(), 36, PURPLE, bold=True, align="center")
    _text(img, (160, 96), clean_name, 30, bold=True, max_width=395, min_size=20)
    if title:
        title_label, title_color = TITLE_DISPLAY.get(title, (title, PURPLE))
        _badge(img, (160, 137), title_label, title_color)
    else:
        _text(img, (160, 143), "Личный профиль", 12, MUTED)
    _text(img, (160, 172), f"ID  {user_id}", 11, DIM, max_width=395)

    li = level_info(xp)
    _rect(img, (40, 202, 560, 274), fill=(29, 29, 47), outline=BORDER)
    _text(img, (58, 219), f"Уровень {li['level']}", 15, bold=True, max_width=145, min_size=12)
    _text(img, (212, 222), level_name(li["level"]), 12, PURPLE, max_width=110)
    level_xp = max(0, xp - li["current_level_xp"])
    level_target = li["next_level_xp"] - li["current_level_xp"]
    _text(img, (542, 222), f"{format_number(level_xp)} / {format_number(level_target)} XP",
          11, MUTED, align="right", max_width=205, min_size=8)
    _progress(img, (58, 250, 542, 256), li["progress"])

    _gradient_panel(img, (40, 292, 376, 407), (48, 38, 77), (31, 31, 50))
    _rect(img, (40, 292, 376, 407), fill=None, outline=(67, 56, 97))
    _gem(img, 66, 320, 8, PURPLE, ton=True)
    _text(img, (84, 315), "БАЛАНС · TON", 10, (191, 175, 228), bold=True)
    _text(img, (58, 350), format_number(balance), 38, bold=True, max_width=300, min_size=18)
    _gradient_panel(img, (390, 292, 560, 407), (44, 30, 48), (30, 27, 43))
    _rect(img, (390, 292, 560, 407), fill=None, outline=(66, 43, 62))
    _gem(img, 415, 320, 8, PINK)
    _text(img, (433, 315), "РУБИНЫ", 10, (220, 164, 190), bold=True)
    _text(img, (408, 350), format_number(rubies), 38, PINK, bold=True, max_width=134, min_size=10)

    _text(img, (40, 431), "Статистика", 20, bold=True)
    _text(img, (560, 438), "ЗА ВСЁ ВРЕМЯ", 9, DIM, align="right")
    _rect(img, (40, 465, 560, 539), fill=PANEL)
    for index, (label, value, color) in enumerate([
        ("Всего игр", total_games, WHITE), ("Победы", wins, GREEN), ("Поражения", losses, PINK),
    ]):
        x = 58 + index * 174
        _text(img, (x, 479), label, 11, MUTED)
        _text(img, (x, 501), format_number(value), 25, color, bold=True, max_width=140, min_size=10)
        if index:
            _line(img, (x - 20, 481, x - 20, 524))

    winrate = wins * 100 / total_games if total_games else 0
    _text(img, (40, 557), "Доля побед", 12, MUTED)
    _text(img, (560, 553), f"{winrate:.1f}%", 18, PURPLE, bold=True, align="right", max_width=180)
    _progress(img, (40, 580, 560, 586), winrate / 100)
    for y, label, value, color in [
        (609, "Общие ставки", total_bet, WHITE),
        (640, "Общий выигрыш", total_won, (236, 208, 150)),
    ]:
        _text(img, (40, y), label, 13, MUTED)
        _text(img, (560, y - 1), f"{format_number(value)} TON", 15, color,
              bold=True, align="right", max_width=320, min_size=10)

    _rect(img, (40, 677, 560, 730), fill=PANEL)
    _text(img, (56, 689), "Достижения", 11, MUTED)
    _text(img, (200, 687), f"{ach_count} / {ach_total}", 14, PURPLE,
          bold=True, max_width=70, align="right", min_size=10)
    _progress(img, (56, 712, 200, 716), ach_count / ach_total if ach_total else 0)
    _line(img, (226, 689, 226, 718))
    _text(img, (246, 698), "Приглашено друзей", 11, MUTED)
    _text(img, (542, 694), format_number(ref_count), 19, WHITE,
          bold=True, align="right", max_width=175, min_size=10)
    _text(img, (300, 746), "TON  /  ТВОЯ ИГРОВАЯ СТАТИСТИКА", 8, DIM, align="center")

    buf = io.BytesIO()
    if len(frames) > 1:
        rendered = []
        for avatar in frames:
            image = img.copy()
            _paste_avatar(image, avatar)
            rendered.append(image)
        # A shared palette keeps the card stable and includes every avatar colour.
        samples = Image.new("RGB", (150 * len(rendered), 195))
        for index, image in enumerate(rendered):
            samples.paste(image.resize((150, 195), Image.Resampling.LANCZOS), (150 * index, 0))
        palette = samples.quantize(colors=256)
        rendered = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in rendered]
        rendered[0].save(buf, format="GIF", save_all=True, append_images=rendered[1:],
                         duration=durations, loop=0, optimize=False, disposal=1)
    else:
        if frames:
            _paste_avatar(img, frames[0])
        img.save(buf, format="PNG", optimize=False)
    buf.seek(0)
    return buf
