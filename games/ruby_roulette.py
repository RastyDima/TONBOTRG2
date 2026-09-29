"""Рубиновая рулетка: ставка рубинами, 3 сектора."""
import secrets

SECTORS = [
    {"name": "Красный", "emoji": "🔴", "mult": 2, "weight": 24},
    {"name": "Чёрный", "emoji": "⚫", "mult": 2, "weight": 24},
    {"name": "Рубин", "emoji": "💎", "mult": 10, "weight": 2},
]

TOTAL_WEIGHT = sum(s["weight"] for s in SECTORS)


class RubyRouletteGame:
    def __init__(self, user_id: int, bet: int):
        self.user_id = user_id
        self.bet = bet
        self.result: dict | None = None
        self.won = False
        self.payout = 0
        self.seed = secrets.token_hex(8)

    def spin(self, choice: str) -> dict:
        roll = secrets.randbelow(TOTAL_WEIGHT) + 1
        acc = 0
        winner = SECTORS[0]
        for s in SECTORS:
            acc += s["weight"]
            if roll <= acc:
                winner = s
                break
        self.result = winner
        self.won = winner["name"].lower() == choice.lower()
        self.payout = self.bet * winner["mult"] if self.won else 0
        return winner

    @property
    def is_over(self) -> bool:
        return self.result is not None

    @property
    def multiplier(self) -> float:
        if self.result and self.won:
            return self.result["mult"]
        return 0
