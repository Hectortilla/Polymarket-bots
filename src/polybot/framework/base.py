from __future__ import annotations

from polybot.framework.context import BotContext
from polybot.framework.events import FillEvent
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.markets import MarketSubscription
from polybot.framework.streams import StreamRule
from polybot.framework.wallets import WalletSubscription


class BaseBot:
    """Subclass this and override only the event hooks your bot needs."""

    async def on_start(self, ctx: BotContext) -> None:
        pass

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return ctx.config.stream_rules

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return ()

    async def current_wallets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[WalletSubscription, ...]:
        rules = await self.current_stream_rules(ctx, now_ms)
        return WalletSubscription.from_addresses(
            tuple(dict.fromkeys(wallet for rule in rules for wallet in rule.wallet_addresses))
        )

    async def current_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        rules = await self.current_stream_rules(ctx, now_ms)
        return MarketSubscription.from_slugs(
            tuple(dict.fromkeys(slug for rule in rules for slug in rule.market_slugs))
        )

    async def next_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        rules = await self.next_stream_rules(ctx, now_ms)
        return MarketSubscription.from_slugs(
            tuple(dict.fromkeys(slug for rule in rules for slug in rule.market_slugs))
        )

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        pass

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        pass

    async def on_fill(self, ctx: BotContext, fill: FillEvent) -> None:
        pass

    async def on_market_resolved(
        self,
        ctx: BotContext,
        event: MarketResolutionEvent,
    ) -> None:
        pass

    def backtest_is_quiescent(self, ctx: BotContext) -> bool:
        """Whether replay may skip remaining events after the portfolio is flat.

        Live runners never consult this hook. Backtest schedulers may use it to
        fast-forward a strategy that has explicitly finished all of its work.
        """
        return False

    async def on_stop(self, ctx: BotContext) -> None:
        pass
