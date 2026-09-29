import math
import secrets

from config import MAX_GAME_MULTIPLIER
from database import db

# Уровни риска: скелетов в трёх дверях (настраиваются множители через админку)
DEFAULT_JOKER_LEVELS = {
    1: {"skulls": 1, "mult": 1.4},
    2: {"skulls": 2, "mult": 2.8},
}

BUTTONS = 3


def get_joker_levels() -> dict:
    """Читает множители уровней из настроек БД (с запасом на отсутствие значений)."""
    levels = {}
    for lvl, cfg in DEFAULT_JOKER_LEVELS.items():
        key = f"joker_mult_{lvl}"
        raw = db.get_setting(key, None)
        try:
            mult = float(raw) if raw is not None else cfg["mult"]
        except (TypeError, ValueError):
            mult = cfg["mult"]
        if not math.isfinite(mult):
            mult = cfg["mult"]
        levels[lvl] = {"skulls": cfg["skulls"], "mult": max(1.0, min(mult, cfg["mult"]))}
    return levels


class JokerGame:
    """Игра «Джокер»: в каждом раунде из трёх дверей в скрыты 💀 скелеты."""

    def __init__(self, user_id: int, bet: int, level: int):
        levels = get_joker_levels()
        if level not in levels:
            raise ValueError("Некорректный уровень риска")
        cfg = levels[level]
        self.type = "joker"
        self.user_id = user_id
        self.bet = bet
        self.level = level
        self.skulls = cfg["skulls"]
        self.round_multiplier = cfg["mult"]
        self.multiplier = 1.0
        self.round = 1
        self.skull_pos = set(secrets.SystemRandom().sample(range(BUTTONS), cfg["skulls"]))
        self.last_pick_pos = None
        self.rounds = []
        self.lost = False
        self.cashed_out = False

    @property
    def is_over(self) -> bool:
        return self.lost or self.cashed_out

    @property
    def payout(self) -> int:
        return int(self.bet * self.multiplier)

    @property
    def can_cashout(self) -> bool:
        return self.round > 1 and not self.is_over

    def pick(self, pos: int) -> str:
        """Открывает дверь pos (0..BUTTONS-1). Возвращает 'safe' или 'skull'."""
        self.last_pick_pos = pos
        skull = pos in self.skull_pos
        self.rounds.append(
            {"skull_pos": set(self.skull_pos), "picked": pos, "result": "skull" if skull else "safe"}
        )
        if skull:
            self.lost = True
            return "skull"
        self.multiplier = min(MAX_GAME_MULTIPLIER, round(self.multiplier * self.round_multiplier, 2))
        self.round += 1
        self.skull_pos = set(secrets.SystemRandom().sample(range(BUTTONS), self.skulls))
        return "safe"

    def reveal_line(self, rd: dict) -> str:
        """Открытые двери раунда: скелеты 💀, выбранная ✅, остальные ⬜."""
        parts = []
        for i in range(BUTTONS):
            if i in rd["skull_pos"]:
                parts.append("💀")
            elif i == rd["picked"]:
                parts.append("✅")
            else:
                parts.append("⬜")
        return "  ".join(parts)

    def hidden_line(self) -> str:
        return "  ".join("❓" for _ in range(BUTTONS))
