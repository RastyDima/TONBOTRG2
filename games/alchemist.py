import secrets

from config import MAX_GAME_MULTIPLIER

# Ингредиенты алхимической лаборатории: (эмодзи, название)
TARGET_RETURN = 0.94

INGREDIENTS = [
    ("🌿", "Тёмная трава"),
    ("🧪", "Эссенция"),
    ("🧄", "Корень"),
    ("🪨", "Лунный камень"),
    ("🍄", "Гриб"),
    ("🌸", "Кровавый цветок"),
]

# Рецепты: frozenset двух индексов -> (эмодзи результата, название зелья, множитель).
# Все пары дают рецепт; удача варки зависит от выбранного режима.
RECIPES = {
    frozenset({0, 1}): ("💎", "Редкое зелье", 2.0),
    frozenset({0, 2}): ("🟢", "Обычное зелье", 1.3),
    frozenset({0, 3}): ("✨", "Магическое зелье", 1.7),
    frozenset({0, 4}): ("🔥", "Нестабильное зелье", 3.0),
    frozenset({0, 5}): ("☠️", "Ядовитый эликсир", 3.6),
    frozenset({1, 2}): ("💰", "Удачное зелье", 1.5),
    frozenset({1, 3}): ("💎", "Редкое зелье", 2.2),
    frozenset({1, 4}): ("💥", "Хаотический экстракт", 3.3),
    frozenset({1, 5}): ("🔥", "Эликсир силы", 2.8),
    frozenset({2, 3}): ("🟢", "Обычное зелье", 1.2),
    frozenset({2, 4}): ("✨", "Необычное зелье", 1.8),
    frozenset({2, 5}): ("☠️", "Проклятое зелье", 3.8),
    frozenset({3, 4}): ("💎", "Легендарное зелье", 4.0),
    frozenset({3, 5}): ("🔥", "Мистическое зелье", 2.5),
    frozenset({4, 5}): ("💥", "Нестабильный эликсир", 4.2),
}

INGREDIENT_COUNT = len(INGREDIENTS)
BREW_MODES = {
    "steady": "Стабилизировать",
    "wild": "Усилить",
}


class AlchemistGame:
    """The recipe and brewing mode determine visible odds before one hidden roll."""

    def __init__(self, user_id: int, bet: int):
        self.type = "alchemist"
        self.user_id = user_id
        self.bet = bet
        self.picks: list[int] = []
        self.result = None
        self.mode = None
        self.brew_multiplier = 0.0
        self.chance_threshold = 0
        self.success = False
        self.lost = False
        self.cashed_out = False

    @property
    def is_over(self) -> bool:
        return self.lost or self.cashed_out

    @property
    def ready(self) -> bool:
        return len(self.picks) == 2

    @property
    def can_cashout(self) -> bool:
        return self.mode is not None and self.success and not self.is_over

    @property
    def recipe(self):
        return RECIPES.get(frozenset(self.picks)) if self.ready else None

    @property
    def brew_options(self) -> dict:
        if not self.ready:
            return {}
        base = self.recipe[2]
        steady = max(1.1, round(base * 0.8, 2))
        wild = min(MAX_GAME_MULTIPLIER, round(base * 1.5, 2))
        return {
            mode: {
                "multiplier": mult,
                "threshold": int(10_000 * TARGET_RETURN / mult),
                "payout": int(self.bet * mult),
            }
            for mode, mult in (("steady", steady), ("wild", wild))
        }

    def pick(self, idx: int) -> bool:
        """Выбирает ингредиент. Возвращает False, если такой уже выбран или уже два."""
        if self.ready or idx in self.picks or not 0 <= idx < INGREDIENT_COUNT:
            return False
        self.picks.append(idx)
        return True

    def choose_mode(self, mode: str) -> bool:
        """Lock the mode and roll exactly once; repeated callbacks cannot reroll."""
        if not self.ready or self.mode is not None or self.is_over or mode not in BREW_MODES:
            return False
        option = self.brew_options[mode]
        self.mode = mode
        self.result = self.recipe
        self.brew_multiplier = option["multiplier"]
        self.chance_threshold = option["threshold"]
        self.success = secrets.randbelow(10_000) < self.chance_threshold
        return True

    @property
    def multiplier(self) -> float:
        return self.brew_multiplier if self.success else 0.0

    @property
    def payout(self) -> int:
        return int(self.bet * self.multiplier)
