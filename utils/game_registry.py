from database import db, level_info, level_name, _calc_level
from utils.achievements import check_achievements

GAME_LABELS = {"mines": "Мины", "joker": "Джокер", "alchemist": "Алхимик", "ruby_roulette": "Рубиновая рулетка", "coinflip": "Монетка", "blackjack": "21"}


class GameRegistry:
    """Хранит активные игры, не позволяя пользователю играть в две сразу."""

    def __init__(self):
        self._active = {}

    def register(self, user_id: int, game_type: str, game) -> bool:
        if self.get(user_id):
            return False
        self._active[user_id] = {"type": game_type, "game": game}
        return True

    def release(self, user_id: int) -> None:
        self._active.pop(user_id, None)

    def is_active(self, user_id: int) -> bool:
        return self.get(user_id) is not None

    def get(self, user_id: int) -> dict | None:
        entry = self._active.get(user_id)
        if entry is None:
            record = db.get_active_mines(user_id)
            if record:
                from games.mines import MinesGame
                entry = {"type": "mines", "game": MinesGame.from_record(record)}
                self._active[user_id] = entry
        return entry

    def game(self, user_id: int):
        entry = self._active.get(user_id)
        return entry["game"] if entry else None


registry = GameRegistry()

# Ставки, которые пользователь задал текстовой командой («м 30000»),
# чтобы они подхватились при выборе количества мин / уровня риска.
_pending_bets: dict[int, int] = {}


def set_pending_bet(user_id: int, bet: int) -> None:
    _pending_bets[user_id] = bet


def get_pending_bet(user_id: int):
    return _pending_bets.pop(user_id, None)


def clear_pending_bet(user_id: int) -> None:
    _pending_bets.pop(user_id, None)


def _process_referral_bet(user_id: int, bet: int) -> None:
    """Начисляет реферальный бонус при ставке реферала."""
    try:
        user = db.get_user(user_id)
        if not user or not user.get("referrer_id"):
            return
        referrer_id = user["referrer_id"]
        bonus = int(bet * 0.05)
        if bonus < 1:
            return
        db.add_balance(referrer_id, bonus, "referral", f"Реферальный бонус от {user_id}")
        db.add_referral_earning(referrer_id, bonus)
    except Exception:
        pass


GAME_XP_PLAY = 5
GAME_XP_WIN = 10


def _check_level_up(user_id: int, old_level: int, new_level: int) -> dict | None:
    """Проверяет повышение уровня. Возвращает info dict или None."""
    if new_level <= old_level:
        return None
    info = level_info(db.get_xp(user_id))
    info["old_level"] = old_level
    info["new_level"] = new_level
    info["level_name"] = level_name(new_level)
    return info


def award_xp(user_id: int, amount: int) -> dict | None:
    """Начисляет XP (2 запроса: чтение + UPDATE...RETURNING).
    Возвращает level-up info dict или None."""
    old_level = _calc_level(db.get_xp(user_id))
    new_xp, new_level = db.add_xp(user_id, amount)
    if new_level <= old_level:
        return None
    info = level_info(new_xp)
    info["old_level"] = old_level
    info["new_level"] = new_level
    info["level_name"] = level_name(new_level)
    return info


def level_up_text(level_up: dict | None) -> str:
    if not level_up:
        return ""
    return f"\n\n🎉 <b>Уровень {level_up['new_level']} — {level_up['level_name']}!</b>"


def award_progress(user_id: int, amount: int) -> dict:
    """Начисляет XP + проверяет ачивки. Возвращает {'level_up', 'achievements'}."""
    return {
        "level_up": award_xp(user_id, amount),
        "achievements": check_achievements(user_id),
    }


def progress_text(progress: dict) -> str:
    """Готовый текст для сообщения из award_progress()."""
    text = level_up_text(progress.get("level_up"))
    for a in progress.get("achievements", []):
        text += f"\n🏅 <b>Достижение: {a['icon']} {a['name']}</b> — {a['desc']}"
    return text


def cashout_game(user_id: int):
    """Забирает выигрыш: начисляет payout, фиксирует победу в БД и статистике."""
    entry = registry.get(user_id)
    if not entry:
        return None
    game = entry["game"]
    if game.is_over or not getattr(game, "can_cashout", True):
        return None
    payout = game.payout
    label = GAME_LABELS.get(entry["type"], entry["type"])
    if entry["type"] == "mines" and game.persisted:
        if not db.settle_mines_round(game, "win"):
            registry.release(user_id)
            return None
    else:
        db.add_balance(user_id, payout, "game_win", f"Выигрыш в игре {label}")
        if payout >= 50000:
            rubies = round(payout / 50000 * 0.1, 2)
            db.add_rubies(user_id, rubies)
    game.cashed_out = True
    _process_referral_bet(user_id, game.bet)
    registry.release(user_id)
    if not (entry["type"] == "mines" and game.persisted):
        db.add_game(user_id, entry["type"], game.bet, payout, "win")
        db.update_stats(user_id, "win", game.bet, payout)
    progress = award_progress(user_id, GAME_XP_PLAY + GAME_XP_WIN)
    return game, payout, progress


def lose_game(user_id: int):
    """Завершает игру поражением: ставка сгорает, фиксирует проигрыш."""
    entry = registry.get(user_id)
    if not entry:
        return None
    game = entry["game"]
    # Some games mark themselves lost when the losing move is revealed.
    # The registry entry, not that flag, determines whether settlement is pending.
    if game.cashed_out:
        return None
    if entry["type"] == "mines" and game.persisted:
        if not db.settle_mines_round(game, "lose"):
            registry.release(user_id)
            return None
    game.lost = True
    _process_referral_bet(user_id, game.bet)
    registry.release(user_id)
    if not (entry["type"] == "mines" and game.persisted):
        db.add_game(user_id, entry["type"], game.bet, 0, "lose")
        db.update_stats(user_id, "lose", game.bet, 0)
    progress = award_progress(user_id, GAME_XP_PLAY)
    return game, progress


def cancel_game(user_id: int):
    """Отменяет игру; после открытой раздачи «21» ставка проигрывается."""
    entry = registry.get(user_id)
    if not entry:
        return None
    game = entry["game"]
    if not getattr(game, "can_refund", True):
        lose_game(user_id)
        return None
    if entry["type"] == "mines" and game.persisted:
        if not db.settle_mines_round(game, "cancel"):
            registry.release(user_id)
            return None
    else:
        db.add_balance(user_id, game.bet, "game_bet", "Возврат ставки")
        db.add_game(user_id, entry["type"], game.bet, game.bet, "cancel")
    registry.release(user_id)
    return game


def draw_game(user_id: int):
    """Ничья в «21»: вернуть ставку без бонусов и повторного начисления XP."""
    entry = registry.get(user_id)
    if not entry or entry["type"] != "blackjack":
        return None
    game = entry["game"]
    if game.outcome != "draw" or game.cashed_out:
        return None
    registry.release(user_id)
    db.add_balance(user_id, game.bet, "game_bet", "Возврат ставки при ничьей в 21")
    db.add_game(user_id, "blackjack", game.bet, game.bet, "draw")
    return game
