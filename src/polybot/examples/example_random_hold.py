from __future__ import annotations

import random
from collections.abc import Callable
from decimal import Decimal
from time import monotonic

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.outcomes import resolve_outcome_token


class ExampleRandomHoldBot(BaseBot):
    """Toy bot that randomly buys Yes or No, holds it, then sells it."""

    def __init__(
        self,
        *,
        market_slug: str | None = None,
        hold_seconds: float = 5.0,
        order_size: Decimal = Decimal("1"),
        rng: random.Random | None = None,
        monotonic_fn: Callable[[], float] = monotonic,
    ) -> None:
        if hold_seconds < 0:
            raise ValueError("hold_seconds must be nonnegative")
        if order_size <= 0:
            raise ValueError("order_size must be positive")
        self.market_slug = market_slug
        self.hold_seconds = hold_seconds
        self.order_size = order_size
        self._rng = rng or random.Random()
        self._monotonic = monotonic_fn
        self._market_slug: str | None = None
        self._condition_id: str | None = None
        self._yes_token_id: str | None = None
        self._no_token_id: str | None = None
        self._selected_token_id: str | None = None
        self._position_size = Decimal("0")
        self._bought_at: float | None = None
        self._sell_in_flight = False

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        if book.market_slug is None or (
            self.market_slug is not None and book.market_slug != self.market_slug
        ):
            return
        await self._load_market(ctx, book.market_slug)
        if self._selected_token_id is None:
            if self._yes_token_id is None or self._no_token_id is None:
                return
            self._selected_token_id = self._rng.choice(
                (self._yes_token_id, self._no_token_id)
            )
        if book.token_id != self._selected_token_id:
            return

        if self._position_size == 0:
            await self._buy(ctx, book)
            return
        if self._sell_in_flight or self._bought_at is None:
            return
        if self._monotonic() - self._bought_at < self.hold_seconds:
            return
        await self._sell(ctx, book)

    async def _load_market(self, ctx: BotContext, market_slug: str) -> None:
        if market_slug == self._market_slug:
            return
        market = await ctx.markets.find_by_slug(market_slug)
        self._market_slug = market_slug
        self._condition_id = None if market is None else market.condition_id
        self._yes_token_id = None if market is None else resolve_outcome_token(market, "Yes")
        self._no_token_id = None if market is None else resolve_outcome_token(market, "No")
        self._selected_token_id = None
        self._position_size = Decimal("0")
        self._bought_at = None
        self._sell_in_flight = False

    async def _buy(self, ctx: BotContext, book: BookSnapshot) -> None:
        if not book.asks:
            return
        ask = min(book.asks, key=lambda level: level.price)
        fill = await ctx.broker.submit(
            OrderRequest(
                token_id=book.token_id,
                side=Side.BUY,
                price=ask.price,
                size=min(self.order_size, ctx.config.max_order_size),
                market_slug=book.market_slug,
                condition_id=self._condition_id,
                reason="random_hold_buy",
            )
        )
        if fill.filled_size > 0:
            self._position_size = fill.filled_size
            self._bought_at = self._monotonic()

    async def _sell(self, ctx: BotContext, book: BookSnapshot) -> None:
        if not book.bids:
            return
        bid = max(book.bids, key=lambda level: level.price)
        self._sell_in_flight = True
        try:
            fill = await ctx.broker.submit(
                OrderRequest(
                    token_id=book.token_id,
                    side=Side.SELL,
                    price=bid.price,
                    size=self._position_size,
                    market_slug=book.market_slug,
                    condition_id=self._condition_id,
                    reason="random_hold_sell",
                )
            )
        finally:
            self._sell_in_flight = False
        self._position_size = max(Decimal("0"), self._position_size - fill.filled_size)
        if self._position_size == 0:
            self._selected_token_id = None
            self._bought_at = None
