from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from decimal import Decimal
from itertools import count
from time import time

from bots.execution.broker import Broker
from bots.execution.orders import taker_fee_usdc
from bots.framework.config import BotConfig
from bots.framework.context import BookClient, MarketClient
from bots.framework.events import (
    BookSnapshot,
    BOOK_PRICE_CEILING,
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
    ZERO_DECIMAL,
)
from .book import consume_levels, slippage_limit_price
from .portfolio import PaperPortfolio

SleepFn = Callable[[float], Awaitable[None]]
NowMsFn = Callable[[], int]

PAPER_ORDER_ID_PREFIX = "paper-"
NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE = "no book depth remained within the slippage cap"
BOOK_UNAVAILABLE_MESSAGE = "fill-time book lookup failed"
BOOK_MISMATCH_MESSAGE = "fill-time book did not match the requested order"
BOOK_STALE_MESSAGE = "fill-time book was stale"
BAD_BOOK_LEVEL_MESSAGE = "fill-time book contained invalid levels"
MARKET_UNAVAILABLE_MESSAGE = "fill-time market metadata was unavailable"
MARKET_FEE_INVALID_MESSAGE = "fill-time market fee rate was invalid"


class PaperBroker(Broker):
    def __init__(
        self,
        config: BotConfig,
        books: BookClient,
        markets: MarketClient | None = None,
        *,
        rng: random.Random | None = None,
        sleep_fn: SleepFn = asyncio.sleep,
        now_ms_fn: NowMsFn | None = None,
    ) -> None:
        self._config = config
        self._books = books
        self._markets = markets
        self._rng = rng or random.Random()
        self._sleep = sleep_fn
        self._now_ms = now_ms_fn or _now_ms
        self._order_ids = count(1)
        self._portfolio = PaperPortfolio(config.paper_portfolio_usdc)
        self._fills_by_source_id: dict[str, FillEvent] = {}

    @property
    def portfolio(self) -> PaperPortfolio:
        return self._portfolio

    async def submit(self, order: OrderRequest) -> FillEvent:
        if order.source_id and (existing_fill := self._fills_by_source_id.get(order.source_id)) is not None:
            return existing_fill

        order_id = f"{PAPER_ORDER_ID_PREFIX}{next(self._order_ids)}"
        validation_reject = self._validate_order(order)
        if validation_reject is not None:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=self._now_ms(),
                reject_reason=validation_reject[0],
                reject_message=validation_reject[1],
            )
            return self._memoize_source_fill(order, fill)

        start_ms = self._now_ms()
        latency_ms = self._sample_latency_ms()
        await self._sleep(latency_ms / 1000)
        fill_time_ms = start_ms + latency_ms

        try:
            book = await self._books.latest(order.token_id)
        except Exception:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=FillRejectReason.BOOK_UNAVAILABLE,
                reject_message=BOOK_UNAVAILABLE_MESSAGE,
            )
            return self._memoize_source_fill(order, fill)

        if book is None:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=FillRejectReason.BOOK_UNAVAILABLE,
                reject_message=BOOK_UNAVAILABLE_MESSAGE,
            )
            return self._memoize_source_fill(order, fill)

        book_reject = self._classify_book(order, book, fill_time_ms)
        if book_reject is not None:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=book_reject,
                reject_message=self._book_reject_message(book_reject),
            )
            return self._memoize_source_fill(order, fill)

        levels = book.executable_levels(order.side)
        slippage_cap = slippage_limit_price(
            side=order.side,
            reference_price=order.price,
            max_slippage_pct=self._config.max_slippage_pct,
        )
        consumed = consume_levels(
            order.side,
            levels,
            requested_size=order.size,
            slippage_limit_price=slippage_cap,
        )
        if not consumed:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=FillRejectReason.NO_DEPTH_WITHIN_SLIPPAGE,
                reject_message=NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE,
            )
            return self._memoize_source_fill(order, fill)

        filled_size = sum((level.size for level in consumed), ZERO_DECIMAL)
        filled_notional = sum(
            (level.notional_usdc for level in consumed),
            ZERO_DECIMAL,
        )
        average_price = filled_notional / filled_size
        fee_rate, fee_reject = await self._resolve_fee_rate(order, book)
        if fee_reject is not None:
            reject_reason, reject_message = fee_reject
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=reject_reason,
                reject_message=reject_message,
            )
            return self._memoize_source_fill(order, fill)
        fee_usdc = sum(
            (
                taker_fee_usdc(
                    shares=level.size,
                    fee_rate=fee_rate,
                    price=level.price,
                )
                for level in consumed
            ),
            ZERO_DECIMAL,
        )

        self._portfolio.apply_fill(
            token_id=order.token_id,
            side=order.side,
            filled_size=filled_size,
            average_price=average_price,
            fee_usdc=fee_usdc,
        )

        status = (
            OrderStatus.FILLED
            if filled_size == order.size
            else OrderStatus.PARTIAL
        )
        fill = FillEvent(
            order_id=order_id,
            token_id=order.token_id,
            side=order.side,
            status=status,
            requested_size=order.size,
            filled_size=filled_size,
            average_price=average_price,
            fee_usdc=fee_usdc,
            received_at_ms=fill_time_ms,
        )
        return self._memoize_source_fill(order, fill)

    async def cancel_all(self) -> None:
        return None

    @staticmethod
    def _validate_order(
        order: OrderRequest,
    ) -> tuple[FillRejectReason, str] | None:
        if not order.token_id:
            return (
                FillRejectReason.MISSING_TOKEN_ID,
                "order is missing token_id",
            )
        if order.side not in (Side.BUY, Side.SELL):
            return (FillRejectReason.BAD_SIDE, "order side is invalid")
        if order.price <= ZERO_DECIMAL or order.price > BOOK_PRICE_CEILING:
            return (FillRejectReason.BAD_PRICE, "order price must be between 0 and 1")
        if order.size <= ZERO_DECIMAL:
            return (FillRejectReason.BAD_SIZE, "order size must be positive")
        return None

    def _classify_book(
        self,
        order: OrderRequest,
        book: BookSnapshot,
        fill_time_ms: int,
    ) -> FillRejectReason | None:
        if book.token_id != order.token_id:
            return FillRejectReason.BOOK_MISMATCH
        if order.market_slug is not None or order.condition_id is not None:
            if book.market_slug is None or book.condition_id is None:
                return FillRejectReason.BOOK_MISMATCH
        if order.market_slug is not None and book.market_slug != order.market_slug:
            return FillRejectReason.BOOK_MISMATCH
        if order.condition_id is not None and book.condition_id != order.condition_id:
            return FillRejectReason.BOOK_MISMATCH
        if not book.is_fresh(fill_time_ms, self._config.book_max_age_ms):
            return FillRejectReason.BOOK_STALE
        if not book.has_valid_levels():
            return FillRejectReason.BAD_BOOK_LEVEL
        return None

    @staticmethod
    def _book_reject_message(reason: FillRejectReason) -> str:
        messages = {
            FillRejectReason.BOOK_MISMATCH: BOOK_MISMATCH_MESSAGE,
            FillRejectReason.BOOK_STALE: BOOK_STALE_MESSAGE,
            FillRejectReason.BAD_BOOK_LEVEL: BAD_BOOK_LEVEL_MESSAGE,
        }
        return messages[reason]

    def _memoize_source_fill(self, order: OrderRequest, fill: FillEvent) -> FillEvent:
        if order.source_id:
            self._fills_by_source_id[order.source_id] = fill
        return fill

    async def _resolve_fee_rate(
        self,
        order: OrderRequest,
        book: BookSnapshot,
    ) -> tuple[Decimal | None, tuple[FillRejectReason, str] | None]:
        market_slug = order.market_slug or book.market_slug
        if market_slug is None:
            return None, (
                FillRejectReason.MARKET_UNAVAILABLE,
                MARKET_UNAVAILABLE_MESSAGE,
            )

        if self._markets is None:
            return None, (
                FillRejectReason.MARKET_UNAVAILABLE,
                MARKET_UNAVAILABLE_MESSAGE,
            )

        try:
            market = await self._markets.find_by_slug(market_slug)
        except Exception:
            return None, (
                FillRejectReason.MARKET_UNAVAILABLE,
                MARKET_UNAVAILABLE_MESSAGE,
            )

        if market is None:
            return None, (
                FillRejectReason.MARKET_UNAVAILABLE,
                MARKET_UNAVAILABLE_MESSAGE,
            )

        try:
            fee_rate = market.fee_rate
        except Exception:
            return None, (
                FillRejectReason.MARKET_FEE_INVALID,
                MARKET_FEE_INVALID_MESSAGE,
            )

        if not isinstance(fee_rate, Decimal):
            return None, (
                FillRejectReason.MARKET_FEE_INVALID,
                MARKET_FEE_INVALID_MESSAGE,
            )
        if fee_rate < ZERO_DECIMAL or fee_rate > BOOK_PRICE_CEILING:
            return None, (
                FillRejectReason.MARKET_FEE_INVALID,
                MARKET_FEE_INVALID_MESSAGE,
            )
        return fee_rate, None

    @staticmethod
    def _rejected_fill(
        order_id: str,
        order: OrderRequest,
        *,
        received_at_ms: int,
        reject_reason: FillRejectReason,
        reject_message: str,
    ) -> FillEvent:
        return FillEvent.rejected(
            order_id=order_id,
            token_id=order.token_id,
            side=order.side,
            requested_size=order.size,
            fee_usdc=ZERO_DECIMAL,
            received_at_ms=received_at_ms,
            reject_reason=reject_reason,
            reject_message=reject_message,
        )

    def _sample_latency_ms(self) -> int:
        if self._config.paper_latency_jitter_ms <= 0:
            return self._config.paper_latency_ms
        jitter_ms = self._rng.randrange(self._config.paper_latency_jitter_ms + 1)
        return self._config.paper_latency_ms + jitter_ms


def _now_ms() -> int:
    return int(time() * 1000)
