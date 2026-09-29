"""Regression checks for game payouts and risk-free cashout."""

import os
import asyncio
import tempfile
import unittest
from math import comb
from pathlib import Path
from unittest.mock import patch

_scratch = tempfile.TemporaryDirectory()
os.environ.update({
    "BOT_TOKEN": "offline-game-tests",
    "RENDER": "false",
    "DATABASE_URL": "",
    "DATABASE_PATH": str(Path(_scratch.name) / "game-tests.db"),
    "ADMIN_PANEL_PASSWORD": "offline-game-tests",
    "WEBHOOK_SECRET": "offline-game-tests",
})

from config import MAX_BET, MAX_GAME_MULTIPLIER  # noqa: E402
from database import db  # noqa: E402
from games.alchemist import AlchemistGame, RECIPES, TARGET_RETURN  # noqa: E402
from games.coinflip import CoinFlipGame  # noqa: E402
from games.joker import JokerGame, get_joker_levels  # noqa: E402
from games.mines import MinesGame, get_house_edge  # noqa: E402
from utils.game_registry import cancel_game, cashout_game, lose_game, registry  # noqa: E402
from utils.helpers import parse_bet  # noqa: E402


class GameBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.register_user(991234, None, "Offline")

    def tearDown(self):
        registry.release(991234)

    def test_bet_limit_and_coinflip_payout(self):
        self.assertEqual(MAX_BET, 250_000)
        self.assertEqual(parse_bet("250k"), MAX_BET)
        self.assertIsNone(parse_bet("250001"))
        with patch("games.coinflip.secrets.choice", return_value="орёл"):
            game = CoinFlipGame(991234, 100)
            game.flip("орёл")
        self.assertEqual(game.payout, 185)
        self.assertLess(0.5 * game.multiplier, 1)

    def test_alchemist_profitable_recipe_is_not_guaranteed(self):
        recipe = RECIPES[frozenset({3, 4})]
        self.assertEqual(recipe[2], 4.0)
        threshold = int(10_000 * TARGET_RETURN / recipe[2])
        self.assertLessEqual(threshold / 10_000 * recipe[2], TARGET_RETURN)
        with patch("games.alchemist.secrets.randbelow", return_value=threshold - 1) as roll:
            win = AlchemistGame(991234, 100)
            win.pick(3); win.pick(4)
            self.assertEqual(win.payout, 400)
            self.assertEqual(win.payout, 400)
            roll.assert_called_once()
        with patch("games.alchemist.secrets.randbelow", return_value=threshold):
            loss = AlchemistGame(991234, 100)
            loss.pick(3); loss.pick(4)
            self.assertEqual(loss.payout, 0)
        for _, _, multiplier in RECIPES.values():
            if multiplier:
                self.assertLessEqual(int(10_000 * TARGET_RETURN / multiplier) / 10_000 * multiplier,
                                     TARGET_RETURN)

    def test_unsafe_saved_settings_are_clamped(self):
        db.set_setting("joker_mult_1", 20)
        db.set_setting("joker_mult_2", 50)
        db.set_setting("mines_house_edge", 2)
        levels = get_joker_levels()
        self.assertEqual(levels[1]["mult"], 1.4)
        self.assertEqual(levels[2]["mult"], 2.8)
        self.assertEqual(get_house_edge(), 0.94)
        self.assertLess((2 / 3) * levels[1]["mult"], 1)
        self.assertLess((1 / 3) * levels[2]["mult"], 1)

    def test_no_cashout_before_a_risky_move(self):
        for game_type, game in (
            ("mines", MinesGame(991234, 100, 1)),
            ("joker", JokerGame(991234, 100, 1)),
        ):
            self.assertTrue(registry.register(991234, game_type, game))
            before = db.get_user(991234)["balance"]
            self.assertIsNone(cashout_game(991234))
            self.assertEqual(db.get_user(991234)["balance"], before)
            registry.release(991234)

    def test_mines_requires_profit_and_caps_multiplier(self):
        game = MinesGame(991234, MAX_BET, 1)
        safe = [cell for cell in range(25) if cell not in game.mine_positions]
        game.revealed.add(safe[0])
        self.assertFalse(game.can_cashout)
        game.revealed.add(safe[1])
        self.assertTrue(game.can_cashout)
        game.revealed.update(safe)
        self.assertLessEqual(game.multiplier, MAX_GAME_MULTIPLIER)
        self.assertLessEqual(game.payout, 2_000_000)

    def test_mines_returns_stay_below_fair_odds(self):
        for mine_count in range(1, 11):
            game = MinesGame(991234, 100, mine_count)
            safe = [cell for cell in range(25) if cell not in game.mine_positions]
            for count, cell in enumerate(safe, 1):
                game.revealed.add(cell)
                survival = comb(25 - count, mine_count) / comb(25, mine_count)
                self.assertLess(survival * game.multiplier, 1)

    def test_joker_loss_is_settled_and_cannot_be_cancelled(self):
        user_id = 991234
        before = db.get_user(user_id)["balance"]
        db.add_balance(user_id, -100, "game_bet", "offline test")
        game = JokerGame(user_id, 100, 1)
        game.skull_pos = {0}
        self.assertTrue(registry.register(user_id, "joker", game))
        self.assertEqual(game.pick(0), "skull")
        self.assertTrue(game.lost)
        self.assertIsNotNone(lose_game(user_id))
        self.assertIsNone(cancel_game(user_id))
        self.assertEqual(db.get_user(user_id)["balance"], before - 100)

    def test_joker_payout_is_capped(self):
        game = JokerGame(991234, MAX_BET, 2)
        for _ in range(5):
            game.skull_pos = {1, 2}
            self.assertEqual(game.pick(0), "safe")
        self.assertEqual(game.multiplier, MAX_GAME_MULTIPLIER)
        self.assertEqual(game.payout, 2_000_000)

    def test_mines_rejects_out_of_field_callback(self):
        from handlers.mines import mines_reveal

        game = MinesGame(991234, 100, 1)
        self.assertTrue(registry.register(991234, "mines", game))

        class FakeUser:
            id = 991234

        class FakeCallback:
            from_user = FakeUser()
            data = "mines_cell:25"

            async def answer(self, text, **kwargs):
                assert text and kwargs.get("show_alert")

        asyncio.run(mines_reveal(FakeCallback()))
        self.assertEqual(game.safe_revealed, 0)


if __name__ == "__main__":
    unittest.main()
