"""Монетка — орёл/решка с небольшим преимуществом банка."""
import secrets

PAYOUT_MULTIPLIER = 1.85


class CoinFlipGame:
    def __init__(self, user_id: int, bet: int):
        self.type = "coinflip"
        self.user_id = user_id
        self.bet = bet
        self.choice: str | None = None
        self.result: str | None = None
        self.won = False
        self.payout = 0
        self.seed = secrets.token_hex(8)

    def flip(self, choice: str) -> str:
        self.choice = choice
        self.result = secrets.choice(["орёл", "решка"])
        self.won = self.result == choice
        self.payout = int(self.bet * PAYOUT_MULTIPLIER) if self.won else 0
        return self.result

    @property
    def is_over(self) -> bool:
        return self.result is not None

    @property
    def multiplier(self) -> float:
        return PAYOUT_MULTIPLIER if self.won else 0
