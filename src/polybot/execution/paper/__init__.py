from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from itertools import count
from time import time

from polybot.async_io import run_blocking

from polybot.execution.broker import Broker
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BookClient, MarketClient
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
)
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent, SettledPosition

from .fill_math import simulate_fill
from .contracts import (
    BAD_BOOK_LEVEL_MESSAGE,
    BOOK_CROSSED_MESSAGE,
    BOOK_FUTURE_DATED_MESSAGE,
    BOOK_MISMATCH_MESSAGE,
    BOOK_STALE_MESSAGE,
    BOOK_UNAVAILABLE_MESSAGE,
    NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE,
    PAPER_ORDER_ID_PREFIX,
)
from .idempotency import DUPLICATE_SOURCE_MESSAGE, SourceIdempotencyStore
from .market_data import (
    MARKET_FEE_INVALID_MESSAGE,
    MARKET_UNAVAILABLE_MESSAGE,
    latest_book,
    resolve_fee_rate,
)
from .latency import sample_latency_ms
from .portfolio import PaperPortfolio, PaperPortfolioSnapshot
from .validation import classify_book, validate_order

SleepFn = Callable[[float], Awaitable[None]]
NowMsFn = Callable[[], int]


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
        self._settled_conditions: set[str] = set()
        self._position_market_refs: dict[str, tuple[str, str]] = {}

    @property
    def portfolio(self) -> PaperPortfolio:
        return self._portfolio

    @property
    def position_market_refs(self) -> dict[str, tuple[str, str]]:
        return self._position_market_refs.copy()

    def snapshot(
        self,
    ) -> tuple[PaperPortfolioSnapshot, set[str], dict[str, tuple[str, str]],]:
        return (
            self._portfolio.snapshot(),
            self._settled_conditions.copy(),
            self._position_market_refs.copy(),
        )

    def restore(
        self,
        snapshot: tuple[
            PaperPortfolioSnapshot,
            set[str],
            dict[str, tuple[str, str]],
        ],
    ) -> None:
        portfolio_snapshot, settled_conditions, position_market_refs = snapshot
        self._portfolio.restore(portfolio_snapshot)
        self._settled_conditions = settled_conditions.copy()
        self._position_market_refs = position_market_refs.copy()

    async def submit(self, order: OrderRequest) -> FillEvent:
        validation_reject = validate_order(order)
        if validation_reject is not None:
            return self._rejected_fill(
                f"{PAPER_ORDER_ID_PREFIX}{next(self._order_ids)}",
                order,
                received_at_ms=self._now_ms(),
                reject_reason=validation_reject[0],
                reject_message=validation_reject[1],
            )
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
            if self._source_store is not None and not await run_blocking(
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
                await run_blocking(self._source_store.release, order.source_id)
            async with self._source_claim_lock:
                if self._fills_by_source_id.get(order.source_id) is claimed_fill:
                    self._fills_by_source_id.pop(order.source_id, None)
            raise

    async def _submit_once(self, order: OrderRequest) -> FillEvent:
        order_id = f"{PAPER_ORDER_ID_PREFIX}{next(self._order_ids)}"
        start_ms = self._now_ms()
        latency_ms = sample_latency_ms(
            self._config.paper_latency_ms,
            self._config.paper_latency_jitter_ms,
            self._rng,
        )
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
            self._config.event_max_age_ms,
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
            raise AssertionError(
                "simulated non-rejected fills require an average price"
            )

        updated_position = self._portfolio.apply_fill(
            token_id=order.token_id,
            side=order.side,
            filled_size=fill.filled_size,
            average_price=fill.average_price,
            fee_usdc=fill.fee_usdc,
        )
        if updated_position.size == 0:
            self._position_market_refs.pop(order.token_id, None)
        else:
            market_slug = order.market_slug or book.market_slug
            condition_id = order.condition_id or book.condition_id
            if market_slug and condition_id:
                self._position_market_refs[order.token_id] = (
                    market_slug,
                    condition_id,
                )
        return fill

    async def cancel_all(self) -> None:
        return None

    def settle_market(
        self,
        event: MarketResolutionEvent,
    ) -> tuple[SettledPosition, ...]:
        if event.condition_id in self._settled_conditions:
            return ()
        settlements = self._portfolio.settle_market(event)
        for token_id in event.token_ids:
            self._position_market_refs.pop(token_id, None)
        self._settled_conditions.add(event.condition_id)
        return settlements

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


def _now_ms() -> int:
    return int(time() * 1000)
