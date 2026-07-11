from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from itertools import count
from time import time

from bots.execution.broker import Broker
from bots.framework.config import BotConfig
from bots.framework.context import BookClient, MarketClient
from bots.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
)
from bots.framework.events.books import BookSnapshot

from .fill_math import simulate_fill
from .idempotency import SourceIdempotencyStore
from .market_data import (
    MARKET_FEE_INVALID_MESSAGE,
    MARKET_UNAVAILABLE_MESSAGE,
    latest_book,
    resolve_fee_rate,
)
from .portfolio import PaperPortfolio
from .validation import classify_book, validate_order

SleepFn = Callable[[float], Awaitable[None]]
NowMsFn = Callable[[], int]

PAPER_ORDER_ID_PREFIX = "paper-"
NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE = "no book depth remained within the slippage cap"
BOOK_UNAVAILABLE_MESSAGE = "fill-time book lookup failed"
BOOK_MISMATCH_MESSAGE = "fill-time book did not match the requested order"
BOOK_STALE_MESSAGE = "fill-time book was stale"
BAD_BOOK_LEVEL_MESSAGE = "fill-time book contained invalid levels"
BOOK_FUTURE_DATED_MESSAGE = "fill-time book was future-dated"
BOOK_CROSSED_MESSAGE = "fill-time book was crossed"
DUPLICATE_SOURCE_MESSAGE = "source event was already processed"


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
        source_store: SourceIdempotencyStore | None = None,
    ) -> None:
        self._config = config
        self._books = books
        self._markets = markets
        self._rng = rng or random.Random()
        self._sleep = sleep_fn
        self._now_ms = now_ms_fn or _now_ms
        self._order_ids = count(1)
        self._portfolio = PaperPortfolio(config.paper_portfolio_usdc)
        self._source_claim_lock = asyncio.Lock()
        self._fills_by_source_id: dict[str, asyncio.Future[FillEvent]] = {}
        self._source_store = source_store

    @property
    def portfolio(self) -> PaperPortfolio:
        return self._portfolio

    async def submit(self, order: OrderRequest) -> FillEvent:
        if not order.source_id:
            return await self._submit_once(order)

        async with self._source_claim_lock:
            claimed_fill = self._fills_by_source_id.get(order.source_id)
            owns_claim = claimed_fill is None
            if owns_claim:
                claimed_fill = asyncio.get_running_loop().create_future()
                self._fills_by_source_id[order.source_id] = claimed_fill

        if not owns_claim:
            return await claimed_fill

        try:
            if self._source_store is not None and not await asyncio.to_thread(
                self._source_store.claim, order.source_id
            ):
                fill = FillEvent.rejected(
                    order_id=f"{PAPER_ORDER_ID_PREFIX}{next(self._order_ids)}",
                    token_id=order.token_id,
                    side=order.side,
                    requested_size=order.size,
                    received_at_ms=self._now_ms(),
                    reject_reason=FillRejectReason.DUPLICATE_SOURCE_ID,
                    reject_message=DUPLICATE_SOURCE_MESSAGE,
                )
                claimed_fill.set_result(fill)
                return fill
            fill = await self._submit_once(order)
            claimed_fill.set_result(fill)
            return fill
        except BaseException as exc:
            if not claimed_fill.done():
                claimed_fill.set_exception(exc)
            if self._source_store is not None:
                await asyncio.to_thread(self._source_store.release, order.source_id)
            async with self._source_claim_lock:
                if self._fills_by_source_id.get(order.source_id) is claimed_fill:
                    self._fills_by_source_id.pop(order.source_id, None)
            raise

    async def _submit_once(self, order: OrderRequest) -> FillEvent:

        order_id = f"{PAPER_ORDER_ID_PREFIX}{next(self._order_ids)}"
        validation_reject = validate_order(order)
        if validation_reject is not None:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=self._now_ms(),
                reject_reason=validation_reject[0],
                reject_message=validation_reject[1],
            )
            return fill

        start_ms = self._now_ms()
        latency_ms = self._sample_latency_ms()
        await self._sleep(latency_ms / 1000)
        book = await latest_book(self._books, order.token_id)
        fill_time_ms = max(start_ms + latency_ms, self._now_ms())
        if book is None:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=FillRejectReason.BOOK_UNAVAILABLE,
                reject_message=BOOK_UNAVAILABLE_MESSAGE,
            )
            return fill

        book_reject = classify_book(
            order,
            book,
            fill_time_ms,
            self._config.book_max_age_ms,
        )
        if book_reject is not None:
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=book_reject,
                reject_message=self._book_reject_message(book_reject),
            )
            return fill

        fee_rate, fee_reject = await resolve_fee_rate(self._markets, order, book)
        if fee_reject is not None:
            reject_reason, reject_message = fee_reject
            fill = self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=reject_reason,
                reject_message=reject_message,
            )
            return fill
        fill = simulate_fill(
            order=order,
            book=book,
            fee_rate=fee_rate,
            max_slippage_pct=self._config.max_slippage_pct,
            order_id=order_id,
            fill_time_ms=fill_time_ms,
        )
        if fill is None:
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=FillRejectReason.NO_DEPTH_WITHIN_SLIPPAGE,
                reject_message=NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE,
            )

        if fill.average_price is None:
            raise AssertionError("simulated non-rejected fills require an average price")

        self._portfolio.apply_fill(
            token_id=order.token_id,
            side=order.side,
            filled_size=fill.filled_size,
            average_price=fill.average_price,
            fee_usdc=fill.fee_usdc,
        )
        return fill

    async def cancel_all(self) -> None:
        return None

    @staticmethod
    def _book_reject_message(reason: FillRejectReason) -> str:
        messages = {
            FillRejectReason.BOOK_MISMATCH: BOOK_MISMATCH_MESSAGE,
            FillRejectReason.BOOK_STALE: BOOK_STALE_MESSAGE,
            FillRejectReason.BOOK_FUTURE_DATED: BOOK_FUTURE_DATED_MESSAGE,
            FillRejectReason.BAD_BOOK_LEVEL: BAD_BOOK_LEVEL_MESSAGE,
            FillRejectReason.BOOK_CROSSED: BOOK_CROSSED_MESSAGE,
        }
        return messages[reason]

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
