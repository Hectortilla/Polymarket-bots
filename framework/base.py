from __future__ import annotations

from bots.framework.context import BotContext
from bots.framework.events import BookSnapshot, FillEvent, WalletTradeEvent
from bots.framework.markets import MarketSubscription, subscriptions_from_slugs
from bots.framework.wallets import (
    WalletSubscription,
    subscriptions_from_addresses,
)


class BaseBot:
    """Subclass this and override only the event hooks your bot needs."""

    async def on_start(self, ctx: BotContext) -> None:
        pass

    async def current_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return subscriptions_from_slugs(ctx.config.market_slugs)

    async def next_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return ()

    async def current_wallets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[WalletSubscription, ...]:
        return subscriptions_from_addresses(ctx.config.wallet_addresses)

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        pass

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        pass

    async def on_fill(self, ctx: BotContext, fill: FillEvent) -> None:
        pass

    async def on_stop(self, ctx: BotContext) -> None:
        pass
