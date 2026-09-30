import math
import random
import secrets
import hashlib
from math import comb

from config import MAX_GAME_MULTIPLIER
from database import db

FIELD_SIZE = 25
ROWS = 5
COLS = 5
MIN_MINES = 1
MAX_MINES = 10


def get_house_edge() -> float:
    """Legacy setting name: payout as a fraction of mathematically fair odds."""
    try:
        value = float(db.get_setting("mines_house_edge", 0.94))
    except (TypeError, ValueError):
        value = 0.94
    return max(0.1, min(value, 0.94)) if math.isfinite(value) else 0.94


class MinesGame:
    """Игра «Мины»: поле 5×5, меняющаяся вероятность и множитель."""

    def __init__(self, user_id: int, bet: int, mines: int):
        if not MIN_MINES <= mines <= MAX_MINES:
            raise ValueError("Некорректное количество мин")
        self.type = "mines"
        self.user_id = user_id
        self.bet = bet
        self.mines = mines
        # Provably fair: позиция мин задаётся крипто-случайным seed'ом в момент
        # старта игры. Пока игра идёт, seed не показывается (иначе мины можно
        # вычислить), а после конца отображается для проверки честности.
        self.seed = secrets.token_hex(16)
        self.seed_hash = hashlib.sha256(self.seed.encode()).hexdigest()
        self.public_id = secrets.token_urlsafe(12)
        rng = random.Random(int(self.seed, 16))
        self.mine_positions = set(rng.sample(range(FIELD_SIZE), mines))
        self.revealed = set()
        self.lost = False
        self.cashed_out = False

    @property
    def is_over(self) -> bool:
        return self.lost or self.cashed_out

    @property
    def safe_revealed(self) -> int:
        return len(self.revealed)

    @property
    def safe_total(self) -> int:
        return FIELD_SIZE - self.mines

    @property
    def can_cashout(self) -> bool:
        return self.safe_revealed > 0 and self.multiplier > 1.0 and not self.is_over

    @property
    def can_refund(self) -> bool:
        return self.safe_revealed == 0 and not self.is_over

    @property
    def multiplier(self) -> float:
        k = self.safe_revealed
        if k == 0:
            return 1.0
        p = comb(FIELD_SIZE - k, self.mines) / comb(FIELD_SIZE, self.mines)
        return min(MAX_GAME_MULTIPLIER, round(get_house_edge() / p, 2))

    @property
    def payout(self) -> int:
        return int(self.bet * self.multiplier)
