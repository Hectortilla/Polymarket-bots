from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.types import market_token_ids

RandomHoldAction = Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class RandomHoldState:
    selected_token_id: str | None
    position_size: Decimal
    bought_at: float | None
    sell_in_flight: bool

    def decision(
        self,
        book: BookSnapshot,
        *,
        now: float,
        hold_seconds: float,
    ) -> RandomHoldAction | None:
        if book.token_id != self.selected_token_id:
            return None
        if self.position_size == 0:
            return "buy"
        if self.sell_in_flight or self.bought_at is None:
            return None
        return "sell" if now - self.bought_at >= hold_seconds else None


class ExampleRandomHoldBot(BaseBot):
    """Toy bot that randomly buys one outcome, holds it, then sells it."""

    def __init__(
        self,
        *,
        market_slug: str | None = None,
        hold_seconds: float = 5.0,
        order_size: Decimal = Decimal("1"),
        rng: random.Random | None = None,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        if hold_seconds < 0:
            raise ValueError("hold_seconds must be nonnegative")
        if order_size <= 0:
            raise ValueError("order_size must be positive")
        self.market_slug = market_slug
        self.hold_seconds = hold_seconds
        self.order_size = order_size
        self._rng = rng
        self._monotonic = monotonic_fn
        self._market_slug: str | None = None
        self._condition_id: str | None = None
        self._token_ids: tuple[str, str] | None = None
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
            if self._token_ids is None:
                return
            rng = self._rng if self._rng is not None else ctx.rng
            self._selected_token_id = rng.choice(self._token_ids)
        action = RandomHoldState(
            self._selected_token_id,
            self._position_size,
            self._bought_at,
            self._sell_in_flight,
        ).decision(book, now=self._now(ctx), hold_seconds=self.hold_seconds)
        if action == "buy":
            await self._buy(ctx, book)
            return
        if action == "sell":
            await self._sell(ctx, book)

    async def _load_market(self, ctx: BotContext, market_slug: str) -> None:
        if market_slug == self._market_slug:
            return
        market = await ctx.markets.find_by_slug(market_slug)
        self._market_slug = market_slug
        self._condition_id = None if market is None else market.condition_id
        self._token_ids = None if market is None else market_token_ids(market)
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
            self._bought_at = self._now(ctx)

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

    def _now(self, ctx: BotContext) -> float:
        if self._monotonic is not None:
            return self._monotonic()
        return ctx.clock.now_ms() / 1000
