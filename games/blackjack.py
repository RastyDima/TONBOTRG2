"""Упрощённая игра «21»: решение взять карту или остановиться."""

import secrets

PAYOUT_MULTIPLIER = 1.9
RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
SUITS = ("♠", "♥", "♦", "♣")


def hand_value(cards: list[tuple[str, str]]) -> int:
    total = 0
    aces = 0
    for rank, _ in cards:
        if rank == "A":
            aces += 1
            total += 11
        elif rank in {"J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackGame:
    def __init__(self, user_id: int, bet: int, deck=None):
        self.type = "blackjack"
        self.user_id = user_id
        self.bet = bet
        self.deck = list(deck) if deck is not None else [
            (rank, suit) for suit in SUITS for rank in RANKS
        ]
        if deck is None:
            secrets.SystemRandom().shuffle(self.deck)
        if len(self.deck) < 4:
            raise ValueError("Колода слишком короткая")
        self.player = [self.deck.pop()]
        self.dealer = [self.deck.pop()]
        self.player.append(self.deck.pop())
        self.dealer.append(self.deck.pop())
        self.turn = 0
        self.outcome: str | None = None
        self.lost = False
        self.cashed_out = False
        # Карты уже открыты игроку: возврат ставки через /cancel дал бы бесплатный перебор.
        self.can_refund = False

    @property
    def player_total(self) -> int:
        return hand_value(self.player)

    @property
    def dealer_total(self) -> int:
        return hand_value(self.dealer)

    @property
    def can_hit(self) -> bool:
        return self.outcome is None and self.player_total < 21

    @property
    def can_cashout(self) -> bool:
        return self.outcome == "win" and not self.cashed_out

    @property
    def is_over(self) -> bool:
        return self.lost or self.cashed_out

    @property
    def payout(self) -> int:
        if self.outcome == "win":
            return int(self.bet * PAYOUT_MULTIPLIER)
        if self.outcome == "draw":
            return self.bet
        return 0

    def hit(self) -> bool:
        if not self.can_hit or not self.deck:
            return False
        self.player.append(self.deck.pop())
        self.turn += 1
        if self.player_total > 21:
            self.outcome = "lose"
            self.lost = True
        elif self.player_total == 21:
            self.stand()
        return True

    def stand(self) -> bool:
        if self.outcome is not None:
            return False
        self.turn += 1
        while self.dealer_total < 17 and self.deck:
            self.dealer.append(self.deck.pop())
        if self.dealer_total > 21 or self.player_total > self.dealer_total:
            self.outcome = "win"
        elif self.player_total == self.dealer_total:
            self.outcome = "draw"
        else:
            self.outcome = "lose"
            self.lost = True
        return True

    def forfeit(self) -> bool:
        if self.outcome is not None:
            return False
        self.outcome = "lose"
        self.lost = True
        self.turn += 1
        return True
