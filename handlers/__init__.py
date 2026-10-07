from . import admin, alchemist, blackjack, coinflip, economy, games, joker, mines, profile, promo, rating, referral, ruby_roulette, shop, start
from . import experience


def register_handlers(dp) -> None:
    for router in (
        promo.router,
        start.router,
        experience.router,
        games.router,
        profile.router,
        economy.router,
        rating.router,
        mines.router,
        joker.router,
        alchemist.router,
        coinflip.router,
        blackjack.router,
        ruby_roulette.router,
        referral.router,
        shop.router,
        admin.router,
    ):
        dp.include_router(router)
