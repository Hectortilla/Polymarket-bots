from __future__ import annotations

from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.outcomes import YES_OUTCOME

PRICE_TRIGGER = Decimal("0.45")


class ExamplePriceWatcher(BaseBot):
    def __init__(
        self,
        outcome_label: str = YES_OUTCOME,
        *,
        market_slug: str | None = None,
    ) -> None:
        self.outcome_label = outcome_label
        self.market_slug = market_slug
        self._market_slug: str | None = None
        self._token_id: str | None = None

    def order_for_book(
        self,
        book: BookSnapshot,
        max_order_size: Decimal,
    ) -> OrderRequest | None:
        if book.token_id != self._token_id or not book.asks:
            return None
        best_ask = min(book.asks, key=lambda level: level.price)
        if best_ask.price > PRICE_TRIGGER:
            return None
        return OrderRequest(
            token_id=self._token_id,
            side=Side.BUY,
            price=best_ask.price,
            size=min(best_ask.size, max_order_size),
        )

    async def on_book(
        self,
        ctx: BotContext,
        book: BookSnapshot,
    ) -> DispatchSkipReason | None:
        if book.market_slug is None or (
            self.market_slug is not None and book.market_slug != self.market_slug
        ):
            return
        if book.market_slug != self._market_slug:
            market = await ctx.markets.find_by_slug(book.market_slug)
            self._market_slug = book.market_slug
            self._token_id = (
                None
                if market is None
                else market.token_id_for_outcome(self.outcome_label)
            )
        if not ctx.is_book_current(book):
            return DispatchSkipReason.BOOK_STALE
        order = self.order_for_book(book, ctx.config.max_order_size)
        if order is not None:
            await ctx.broker.submit(order)
