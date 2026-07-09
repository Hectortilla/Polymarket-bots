from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.events import BookSnapshot, OrderRequest, Side
from bots.framework.markets import MarketSubscription


@dataclass(frozen=True, slots=True)
class CrossMarketRule:
    signal_slug: str
    target_slug: str
    target_token_id: str
    trigger_price: Decimal
    order_price: Decimal
    max_size: Decimal


class ExampleMultiMarketBot(BaseBot):
    def __init__(self, rules: tuple[CrossMarketRule, ...]) -> None:
        self.rules = rules

    async def current_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        slugs = {rule.signal_slug for rule in self.rules}
        slugs.update(rule.target_slug for rule in self.rules)
        return tuple(MarketSubscription(slug=slug) for slug in sorted(slugs))

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        if book.market_slug is None or not book.asks:
            return

        best_ask = book.asks[0]
        for rule in self.rules:
            if book.market_slug != rule.signal_slug:
                continue
            if best_ask.price > rule.trigger_price:
                continue

            await ctx.broker.submit(
                OrderRequest(
                    token_id=rule.target_token_id,
                    side=Side.BUY,
                    price=rule.order_price,
                    size=min(rule.max_size, ctx.config.max_order_size),
                    market_slug=rule.target_slug,
                    reason=f"cross_market_signal:{rule.signal_slug}",
                )
            )
