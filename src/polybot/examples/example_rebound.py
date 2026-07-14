from __future__ import annotations

from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import YES_OUTCOME
from polybot.framework.outcomes import resolve_outcome_token


class ReboundState:
    def __init__(
        self, last_price: Decimal | None = None, saw_decline: bool = False
    ) -> None:
        self.last_price = last_price
        self.saw_decline = saw_decline

    def order_for_book(
        self,
        book: BookSnapshot,
        *,
        token_id: str | None,
        order_size: Decimal,
        max_order_size: Decimal,
    ) -> tuple[OrderRequest | None, ReboundState]:
        if book.token_id != token_id or not book.asks:
            return None, self
        current_price = min(book.asks, key=lambda level: level.price).price
        if self.last_price is None:
            return None, ReboundState(current_price)
        if current_price < self.last_price:
            return None, ReboundState(current_price, True)
        if not self.saw_decline or current_price <= self.last_price:
            return None, ReboundState(current_price, self.saw_decline)
        return (
            OrderRequest(
                token_id=token_id,
                side=Side.BUY,
                price=current_price,
                size=min(order_size, max_order_size),
                market_slug=book.market_slug,
                condition_id=book.condition_id,
                reason="price_rebound",
            ),
            ReboundState(current_price),
        )


class ExampleReboundBot(BaseBot):
    """Tutorial bot: buy after a fall followed by a small rebound.

    This is intentionally a toy signal. It uses the best ask as the observed
    price and does not try to predict whether the rebound will continue.
    """

    def __init__(
        self,
        outcome_label: str = YES_OUTCOME,
        *,
        market_slug: str | None = None,
        order_size: Decimal = Decimal("1"),
    ) -> None:
        self.outcome_label = outcome_label
        self.market_slug = market_slug
        self.order_size = order_size
        self._market_slug: str | None = None
        self._token_id: str | None = None
        self._rebound_state = ReboundState()

    def order_for_book(
        self,
        book: BookSnapshot,
        max_order_size: Decimal,
    ) -> OrderRequest | None:
        order, self._rebound_state = self._rebound_state.order_for_book(
            book,
            token_id=self._token_id,
            order_size=self.order_size,
            max_order_size=max_order_size,
        )
        return order

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
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
                else resolve_outcome_token(market, self.outcome_label)
            )
            self._rebound_state = ReboundState()
        order = self.order_for_book(book, ctx.config.max_order_size)
        if order is not None:
            await ctx.broker.submit(order)
