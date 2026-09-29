import secrets

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
# Множитель None означает проигрыш (смесь взрывается/отравляет).
RECIPES = {
    frozenset({0, 1}): ("💎", "Редкое зелье", 2.0),
    frozenset({0, 2}): ("🟢", "Обычное зелье", 1.3),
    frozenset({0, 3}): ("✨", "Магическое зелье", 1.7),
    frozenset({0, 4}): ("🔥", "Нестабильное зелье", 3.0),
    frozenset({0, 5}): ("☠️", "Ядовитая смесь", None),
    frozenset({1, 2}): ("💰", "Удачное зелье", 1.5),
    frozenset({1, 3}): ("💎", "Редкое зелье", 2.2),
    frozenset({1, 4}): ("☠️", "Взрыв", None),
    frozenset({1, 5}): ("🔥", "Эликсир силы", 2.8),
    frozenset({2, 3}): ("🟢", "Обычное зелье", 1.2),
    frozenset({2, 4}): ("✨", "Необычное зелье", 1.8),
    frozenset({2, 5}): ("☠️", "Проклятое зелье", None),
    frozenset({3, 4}): ("💎", "Легендарное зелье", 4.0),
    frozenset({3, 5}): ("🔥", "Мистическое зелье", 2.5),
    frozenset({4, 5}): ("☠️", "Нестабильная реакция", None),
}

INGREDIENT_COUNT = len(INGREDIENTS)


class AlchemistGame:
    """Recipe determines the prize; a hidden roll determines whether it succeeds."""

    def __init__(self, user_id: int, bet: int):
        self.type = "alchemist"
        self.user_id = user_id
        self.bet = bet
        self.picks: list[int] = []
        self.result = None
        self.success = False
        self.lost = False
        self.cashed_out = False

    @property
    def is_over(self) -> bool:
        return self.lost or self.cashed_out

    @property
    def ready(self) -> bool:
        return len(self.picks) == 2

    def pick(self, idx: int) -> bool:
        """Выбирает ингредиент. Возвращает False, если такой уже выбран или уже два."""
        if self.ready or idx in self.picks or not 0 <= idx < INGREDIENT_COUNT:
            return False
        self.picks.append(idx)
        return True

    def resolve(self):
        """Вычисляет результат смешивания (только когда выбраны оба ингредиента)."""
        if not self.ready:
            return None
        if self.result is None:
            self.result = RECIPES.get(frozenset(self.picks))
            if self.result and self.result[2]:
                threshold = int(10_000 * TARGET_RETURN / self.result[2])
                self.success = secrets.randbelow(10_000) < threshold
        return self.result

    @property
    def multiplier(self) -> float:
        result = self.resolve()
        if not result or not self.success:
            return 0.0
        return result[2]

    @property
    def payout(self) -> int:
        return int(self.bet * self.multiplier)
