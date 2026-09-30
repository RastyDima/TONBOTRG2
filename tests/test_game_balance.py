"""Regression checks for game payouts and risk-free cashout."""

import os
import asyncio
import tempfile
import unittest
from math import comb
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
from games.blackjack import BlackjackGame, PAYOUT_MULTIPLIER as BLACKJACK_PAYOUT, hand_value  # noqa: E402
from games.coinflip import CoinFlipGame  # noqa: E402
from games.joker import JokerGame, get_joker_levels  # noqa: E402
from games.mines import MinesGame, get_house_edge  # noqa: E402
from utils.game_registry import cancel_game, cashout_game, draw_game, lose_game, registry  # noqa: E402
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

    def test_blackjack_aces_deck_and_payout_cap(self):
        self.assertEqual(hand_value([("A", "♠"), ("A", "♥"), ("9", "♦")]), 21)
        game = BlackjackGame(991234, MAX_BET)
        self.assertEqual(len(set(game.player + game.dealer + game.deck)), 52)
        self.assertEqual(len(game.deck), 48)
        self.assertEqual(BLACKJACK_PAYOUT, 1.9)
        self.assertLessEqual(int(MAX_BET * BLACKJACK_PAYOUT), 475_000)

    def test_blackjack_win_settles_once_and_stale_button_cannot_replay(self):
        from handlers.blackjack import blackjack_action

        user_id = 991234
        before = db.get_user(user_id)["balance"]
        # Draw order from right: player 10, dealer A, player 9, dealer 7.
        deck = [("7", "♣"), ("9", "♦"), ("A", "♥"), ("10", "♠")]
        game = BlackjackGame(user_id, 100, deck=deck)
        db.add_balance(user_id, -100, "game_bet", "offline test")
        self.assertTrue(registry.register(user_id, "blackjack", game))
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            data="bj:stand:0",
            answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock()),
        )
        asyncio.run(blackjack_action(callback))
        self.assertEqual(game.outcome, "win")
        self.assertEqual(db.get_user(user_id)["balance"], before + 90)
        self.assertIsNone(registry.game(user_id))
        asyncio.run(blackjack_action(callback))
        self.assertEqual(db.get_user(user_id)["balance"], before + 90)
        self.assertIsNone(cancel_game(user_id))

    def test_blackjack_draw_refunds_once_without_progress(self):
        from handlers.blackjack import blackjack_action

        user_id = 991234
        before = db.get_user(user_id)["balance"]
        deck = [("8", "♣"), ("8", "♥"), ("10", "♣"), ("10", "♠")]
        game = BlackjackGame(user_id, 100, deck=deck)
        db.add_balance(user_id, -100, "game_bet", "offline test")
        self.assertTrue(registry.register(user_id, "blackjack", game))
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            data="bj:stand:0",
            answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock()),
        )
        asyncio.run(blackjack_action(callback))
        self.assertEqual(game.outcome, "draw")
        self.assertEqual(db.get_user(user_id)["balance"], before)
        self.assertIsNone(draw_game(user_id))
        self.assertIsNone(registry.game(user_id))

    def test_blackjack_cancel_after_deal_forfeits_bet(self):
        user_id = 991234
        before = db.get_user(user_id)["balance"]
        game = BlackjackGame(user_id, 100)
        db.add_balance(user_id, -100, "game_bet", "offline test")
        self.assertTrue(registry.register(user_id, "blackjack", game))
        self.assertIsNone(cancel_game(user_id))
        self.assertEqual(db.get_user(user_id)["balance"], before - 100)
        self.assertIsNone(registry.game(user_id))

    def test_blackjack_rejects_repeated_hit_from_old_button(self):
        from handlers.blackjack import blackjack_action

        user_id = 991234
        deck = [("2", "♣"), ("7", "♣"), ("4", "♥"), ("10", "♣"), ("5", "♠")]
        game = BlackjackGame(user_id, 100, deck=deck)
        self.assertTrue(registry.register(user_id, "blackjack", game))
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            data="bj:hit:0",
            answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock()),
        )
        asyncio.run(blackjack_action(callback))
        self.assertEqual(game.turn, 1)
        self.assertEqual(len(game.player), 3)
        asyncio.run(blackjack_action(callback))
        self.assertEqual(len(game.player), 3)
        self.assertEqual(game.turn, 1)

    def test_alchemist_modes_show_odds_and_roll_once(self):
        recipe = RECIPES[frozenset({3, 4})]
        self.assertEqual(recipe[2], 4.0)
        win = AlchemistGame(991234, 100)
        self.assertFalse(win.choose_mode("steady"))
        win.pick(3); win.pick(4)
        self.assertFalse(win.can_cashout)
        steady = win.brew_options["steady"]
        wild = win.brew_options["wild"]
        self.assertGreater(steady["threshold"], wild["threshold"])
        self.assertLess(steady["payout"], wild["payout"])
        with patch("games.alchemist.secrets.randbelow", return_value=steady["threshold"] - 1) as roll:
            self.assertTrue(win.choose_mode("steady"))
            self.assertFalse(win.choose_mode("wild"))
            self.assertEqual(win.payout, steady["payout"])
            self.assertTrue(win.can_cashout)
            roll.assert_called_once()
        with patch("games.alchemist.secrets.randbelow", return_value=wild["threshold"]):
            loss = AlchemistGame(991234, 100)
            loss.pick(3); loss.pick(4)
            self.assertTrue(loss.choose_mode("wild"))
            self.assertEqual(loss.payout, 0)
        for picks in RECIPES:
            game = AlchemistGame(991234, 100)
            for pick in picks:
                game.pick(pick)
            for option in game.brew_options.values():
                self.assertLessEqual(option["threshold"] / 10_000 * option["multiplier"],
                                     TARGET_RETURN + 1e-10)
                self.assertLessEqual(option["multiplier"], MAX_GAME_MULTIPLIER)

    def test_alchemist_settles_before_animation_and_cannot_be_refunded(self):
        from handlers.alchemist import alchemist_brew

        user_id = 991234
        before = db.get_user(user_id)["balance"]
        db.add_balance(user_id, -100, "game_bet", "offline test")
        game = AlchemistGame(user_id, 100)
        game.pick(3); game.pick(4)
        self.assertTrue(registry.register(user_id, "alchemist", game))

        class FakeUser:
            id = user_id

        class FakeCallback:
            from_user = FakeUser()
            data = "alch_brew:steady"

        animation = AsyncMock()
        with patch("games.alchemist.secrets.randbelow", return_value=9999), \
             patch("handlers.alchemist.finish_mix", animation):
            asyncio.run(alchemist_brew(FakeCallback()))
        self.assertTrue(game.lost)
        self.assertIsNone(registry.game(user_id))
        self.assertIsNone(cancel_game(user_id))
        self.assertEqual(db.get_user(user_id)["balance"], before - 100)
        animation.assert_awaited_once()

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

    def test_joker_can_switch_risk_between_rounds(self):
        game = JokerGame(991234, 100, 1)
        game.skull_pos = {2}
        self.assertEqual(game.pick(0), "safe")
        self.assertEqual(game.payout, 140)
        self.assertEqual(game.rounds[0]["level"], 1)

        self.assertTrue(game.set_level(2))
        self.assertEqual(game.skulls, 2)
        self.assertEqual(game.next_payout, 392)
        game.skull_pos = {1, 2}
        self.assertEqual(game.pick(0), "safe")
        self.assertEqual(game.rounds[1]["level"], 2)
        self.assertEqual(game.payout, 392)
        self.assertFalse(game.set_level(3))

        game.skull_pos = {0, 2}
        self.assertEqual(game.pick(0), "skull")
        self.assertFalse(game.set_level(1))

    def test_joker_each_risk_has_house_edge(self):
        levels = get_joker_levels()
        for cfg in levels.values():
            success_chance = (3 - cfg["skulls"]) / 3
            self.assertLess(success_chance * cfg["mult"], 1)

    def test_joker_rejects_stale_round_buttons(self):
        from handlers.joker import joker_change_risk, joker_pick

        game = JokerGame(991234, 100, 1)
        self.assertTrue(registry.register(991234, "joker", game))

        class FakeUser:
            id = 991234

        class FakeCallback:
            from_user = FakeUser()
            data = "joker_risk:0:2"

            async def answer(self, text, **kwargs):
                assert text and kwargs.get("show_alert")

        callback = FakeCallback()
        asyncio.run(joker_change_risk(callback))
        self.assertEqual(game.level, 1)
        callback.data = "joker_pick:0:0"
        asyncio.run(joker_pick(callback))
        self.assertEqual(game.rounds, [])

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
