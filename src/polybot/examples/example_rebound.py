from __future__ import annotations

from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.outcomes import resolve_outcome_token


class ExampleReboundBot(BaseBot):
    """Tutorial bot: buy after a fall followed by a small rebound.

    This is intentionally a toy signal. It uses the best ask as the observed
    price and does not try to predict whether the rebound will continue.
    """

    def __init__(self, outcome_label: str = "Yes", *, market_slug: str | None = None, order_size: Decimal = Decimal("1")) -> None:
        self.outcome_label = outcome_label
        self.market_slug = market_slug
        self.order_size = order_size
        self._market_slug: str | None = None
        self._token_id: str | None = None
        self._last_price: Decimal | None = None
        self._saw_decline = False

    def order_for_book(
        self,
        book: BookSnapshot,
        max_order_size: Decimal,
    ) -> OrderRequest | None:
        if book.token_id != self._token_id or not book.asks:
            return None

        current_price = min(book.asks, key=lambda level: level.price).price
        previous_price = self._last_price
        self._last_price = current_price

        if previous_price is None:
            return None
        if current_price < previous_price:
            self._saw_decline = True
            return None
        if not self._saw_decline or current_price <= previous_price:
            return None

        self._saw_decline = False
        return OrderRequest(
            token_id=self._token_id,
            side=Side.BUY,
            price=current_price,
            size=min(self.order_size, max_order_size),
            market_slug=book.market_slug,
            condition_id=book.condition_id,
            reason="price_rebound",
        )

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        if book.market_slug is None or (
            self.market_slug is not None and book.market_slug != self.market_slug
        ):
            return
        if book.market_slug != self._market_slug:
            market = await ctx.markets.find_by_slug(book.market_slug)
            self._market_slug = book.market_slug
            self._token_id = (
                None if market is None else resolve_outcome_token(market, self.outcome_label)
            )
            self._last_price = None
            self._saw_decline = False
        order = self.order_for_book(book, ctx.config.max_order_size)
        if order is not None:
            await ctx.broker.submit(order)
