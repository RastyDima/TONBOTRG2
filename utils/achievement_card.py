"""Render the achievement collection in the same visual style as the profile."""

import io
import math
from collections.abc import Iterable

from PIL import Image, ImageDraw

from utils.achievements import ACHIEVEMENTS
from utils.profile_card import (
    BORDER, DIM, GREEN, MUTED, PANEL, PURPLE, SCALE, WHITE,
    _gem, _gradient_panel, _line, _progress, _rect, _text, _width,
)

GOLD = (236, 208, 150)
ICONS = {
    "first_game": "game", "grinder_10": "game", "grinder_100": "game",
    "first_win": "trophy", "winner_10": "trophy", "winner_50": "trophy",
    "turnover_100k": "coins", "turnover_1m": "coins", "rich_100k": "gem",
    "referrer": "people", "magnet": "people", "level_5": "star",
    "bonus_hunter": "gift", "shopper": "bag",
}


def _icon(img, x, y, kind, color, size=24):
    """Draw small vector-style symbols without depending on emoji fonts."""
    draw = ImageDraw.Draw(img)
    unit = size / 24

    def points(values):
        return [((x + px * unit) * SCALE, (y + py * unit) * SCALE) for px, py in values]

    def line(values):
        draw.line(points(values), fill=color, width=max(2, round(1.6 * unit * SCALE)), joint="curve")

    def ellipse(box):
        draw.ellipse([points([(box[0], box[1])])[0], points([(box[2], box[3])])[0]],
                     outline=color, width=max(2, round(1.6 * unit * SCALE)))

    def rect(box, radius=2):
        draw.rounded_rectangle([points([(box[0], box[1])])[0], points([(box[2], box[3])])[0]],
                               radius=radius * unit * SCALE, outline=color,
                               width=max(2, round(1.6 * unit * SCALE)))

    if kind == "trophy":
        line([(6, 3), (18, 3), (17, 12), (14, 15), (10, 15), (7, 12), (6, 3)])
        line([(6, 5), (2, 5), (2, 9), (4, 12), (7, 12)])
        line([(18, 5), (22, 5), (22, 9), (20, 12), (17, 12)])
        line([(12, 15), (12, 20)])
        line([(7, 21), (17, 21)])
    elif kind == "game":
        rect((2, 6, 22, 19), 4)
        line([(5, 12), (11, 12)])
        line([(8, 9), (8, 15)])
        ellipse((15, 9, 17, 11))
        ellipse((18, 13, 20, 15))
    elif kind == "coins":
        ellipse((3, 3, 17, 9))
        line([(3, 6), (3, 16), (6, 19), (14, 19), (17, 16), (17, 6)])
        line([(3, 11), (6, 14), (14, 14), (17, 11)])
        line([(20, 9), (22, 11), (22, 19), (19, 22), (12, 22)])
    elif kind == "gem":
        line([(6, 3), (18, 3), (23, 9), (12, 22), (1, 9), (6, 3)])
        line([(1, 9), (23, 9)])
        line([(8, 3), (7, 9), (12, 22), (17, 9), (16, 3)])
    elif kind == "people":
        ellipse((5, 3, 13, 11))
        line([(2, 21), (2, 17), (5, 14), (13, 14), (16, 17), (16, 21)])
        line([(16, 4), (19, 5), (20, 8), (18, 11)])
        line([(19, 14), (22, 17), (22, 21)])
    elif kind == "gift":
        rect((3, 10, 21, 15), 1)
        line([(5, 15), (5, 22), (19, 22), (19, 15)])
        line([(12, 10), (12, 22)])
        line([(12, 10), (6, 8), (5, 5), (8, 3), (11, 6), (12, 10),
              (13, 6), (16, 3), (19, 5), (18, 8), (12, 10)])
    elif kind == "bag":
        rect((4, 8, 20, 22), 2)
        line([(8, 10), (8, 5), (10, 2), (14, 2), (16, 5), (16, 10)])
    else:
        vertices = []
        for index in range(10):
            angle = math.radians(index * 36 - 90)
            radius = 10 if index % 2 == 0 else 4.5
            vertices.append((12 + radius * math.cos(angle), 12 + radius * math.sin(angle)))
        line(vertices + vertices[:1])


def _description(img, x, y, text, width, color):
    """Wrap descriptions into two legible lines inside each tile."""
    words = str(text).split()
    lines = [""]
    for word in words:
        candidate = (lines[-1] + " " + word).strip()
        if _width(candidate, 11, False) > width and lines[-1] and len(lines) == 1:
            lines.append(word)
        else:
            lines[-1] = candidate
    for index, line in enumerate(lines):
        _text(img, (x, y + index * 14), line, 11, color, max_width=width)


def generate_achievements_card(user_id: int, name: str, owned: Iterable[str]) -> io.BytesIO:
    """Return a rewound PNG; only saved, currently defined awards count as earned."""
    earned = set(owned).intersection(ACHIEVEMENTS)
    total, count = len(ACHIEVEMENTS), len(earned)
    rows = max(1, math.ceil(total / 2))
    height = 376 + rows * 96
    img = Image.new("RGB", (600 * SCALE, height * SCALE), (12, 14, 23))
    _gradient_panel(img, (16, 16, 584, height - 16), (25, 25, 43), (17, 21, 32), radius=28)
    _rect(img, (16, 16, 584, height - 16), fill=None, radius=28, outline=BORDER)
    _gem(img, 49, 47, 8, PURPLE, ton=True)
    _text(img, (66, 40), "TON", 14, bold=True)
    _text(img, (560, 43), "КОЛЛЕКЦИЯ НАГРАД", 10, MUTED, align="right")
    _line(img, (40, 69, 560, 69))

    _gradient_panel(img, (40, 90, 104, 154), (66, 51, 66), (42, 36, 55), radius=18)
    _icon(img, 52, 100, "trophy", GOLD, size=40)
    _text(img, (124, 94), "Достижения", 31, bold=True)
    _text(img, (124, 136), name or "Игрок", 14, MUTED, max_width=436)

    _rect(img, (40, 181, 560, 269), fill=(29, 29, 47), outline=BORDER)
    _text(img, (58, 198), "Открыто достижений", 11, MUTED)
    _text(img, (58, 221), f"{count} / {total}", 29, bold=True, max_width=145, min_size=18)
    remaining = f"Осталось {total - count}" if count < total else "Коллекция собрана"
    if not total:
        remaining = "Коллекция пополняется"
    _text(img, (542, 198), remaining, 11, GREEN if total and count == total else PURPLE, align="right")
    _progress(img, (220, 235, 542, 242), count / total if total else 0)

    _text(img, (40, 293), "Все достижения", 16, bold=True)
    _text(img, (560, 298), "ПОЛУЧЕНО" if total and count == total else "ОТКРЫВАЙ НОВЫЕ НАГРАДЫ",
          9, DIM, align="right")

    for index, (achievement_id, achievement) in enumerate(ACHIEVEMENTS.items()):
        x, y = 40 + (index % 2) * 267, 327 + (index // 2) * 96
        unlocked = achievement_id in earned
        if unlocked:
            _gradient_panel(img, (x, y, x + 253, y + 86), (40, 35, 61), (29, 30, 47), radius=14)
            _rect(img, (x, y, x + 253, y + 86), fill=None, radius=14, outline=(64, 57, 86))
        else:
            _rect(img, (x, y, x + 253, y + 86), fill=PANEL, radius=14)
        _rect(img, (x + 14, y + 13, x + 46, y + 45),
              fill=(55, 47, 67) if unlocked else (35, 37, 53), radius=10)
        _icon(img, x + 20, y + 19, ICONS.get(achievement_id, "star"), GOLD if unlocked else DIM, size=20)
        _text(img, (x + 58, y + 15), achievement["name"], 13,
              WHITE if unlocked else MUTED, bold=True, max_width=181, min_size=11)
        _text(img, (x + 58, y + 35), "ПОЛУЧЕНО" if unlocked else "ЗАКРЫТО",
              8, GREEN if unlocked else DIM, bold=True)
        _description(img, x + 14, y + 55, achievement["desc"], 225, MUTED)

    if not total:
        _text(img, (300, 359), "Новые достижения скоро появятся", 15, MUTED, align="center")
    _text(img, (40, height - 40), f"ID  {user_id}", 9, DIM, max_width=200)
    _text(img, (560, height - 40), "TON  /  ТВОЯ КОЛЛЕКЦИЯ", 9, DIM, align="right")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    buf.seek(0)
    return buf
