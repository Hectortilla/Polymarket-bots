from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from itertools import count

from polybot.async_io import run_blocking
from polybot.execution.broker import Broker
from polybot.framework.clock import Clock, ClockDataExhaustedError, SystemClock
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
    BACKTEST_COVERAGE_GAP_MESSAGE,
    BACKTEST_DATA_EXHAUSTED_MESSAGE,
    BOOK_CROSSED_MESSAGE,
    BOOK_FUTURE_DATED_MESSAGE,
    BOOK_MISMATCH_MESSAGE,
    BOOK_STALE_MESSAGE,
    BOOK_UNAVAILABLE_MESSAGE,
    NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE,
    PAPER_ORDER_ID_PREFIX,
)
from .continuity import BookContinuity, BookContinuitySource
from .idempotency import DUPLICATE_SOURCE_MESSAGE, SourceIdempotencyStore
from .market_data import (
    FillMarketData,
    MARKET_FEE_INVALID_MESSAGE,
    MARKET_UNAVAILABLE_MESSAGE,
    MARKET_RESOLVED_MESSAGE,
    latest_book,
    resolve_fill_market_data,
    validate_fill_market_data,
)
from .latency import latency_ms
from .portfolio import PaperPortfolio, PaperPortfolioSnapshot
from .validation import classify_book, validate_order

SleepFn = Callable[[float], Awaitable[None]]
NowMsFn = Callable[[], int]


@dataclass(frozen=True, slots=True)
class _BookFillInput:
    """One book snapshot validated at the current fill-time boundary."""

    book: BookSnapshot
    fill_time_ms: int


class PaperBroker(Broker):
    def __init__(
        self,
        config: BotConfig,
        books: BookClient,
        markets: MarketClient | None = None,
        *,
        rng: random.Random | None = None,
        clock: Clock | None = None,
        sleep_fn: SleepFn | None = None,
        now_ms_fn: NowMsFn | None = None,
        source_store: SourceIdempotencyStore | None = None,
        continuity_source: BookContinuitySource | None = None,
    ) -> None:
        if clock is not None and (sleep_fn is not None or now_ms_fn is not None):
            raise ValueError("clock cannot be combined with sleep_fn or now_ms_fn")
        runtime_clock = clock if clock is not None else SystemClock()
        self._config = config
        self._books = books
        self._markets = markets
        self._rng = rng if rng is not None else random.Random()
        self._sleep = sleep_fn if sleep_fn is not None else runtime_clock.sleep
        self._now_ms = now_ms_fn if now_ms_fn is not None else runtime_clock.now_ms
        self._order_ids = count(1)
        self._portfolio = PaperPortfolio(config.paper_portfolio_usdc)
        self._source_claim_lock = asyncio.Lock()
        self._fills_by_source_id: dict[str, asyncio.Future[FillEvent]] = {}
        self._source_store = source_store
        self._continuity_source = continuity_source
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
            # A caller may cancel without abandoning the shared source-id claim.
            return await asyncio.shield(claimed_fill)

        source_claimed = False
        try:
            if self._source_store is not None:
                source_claimed = await run_blocking(
                    self._source_store.claim, order.source_id
                )
            if self._source_store is not None and not source_claimed:
                fill = FillEvent.rejected(
                    order_id=f"{PAPER_ORDER_ID_PREFIX}{next(self._order_ids)}",
                    token_id=order.token_id,
                    side=order.side,
                    requested_size=order.size,
                    received_at_ms=self._now_ms(),
                    reject_reason=FillRejectReason.DUPLICATE_SOURCE_ID,
                    reject_message=DUPLICATE_SOURCE_MESSAGE,
                )
                _complete_claim(claimed_fill, fill)
                return fill
            fill = await self._submit_once(order)
            _complete_claim(claimed_fill, fill)
            return fill
        except BaseException as exc:
            if not claimed_fill.done():
                claimed_fill.set_exception(exc)
            if self._source_store is not None and source_claimed:
                await run_blocking(self._source_store.release, order.source_id)
            async with self._source_claim_lock:
                if self._fills_by_source_id.get(order.source_id) is claimed_fill:
                    self._fills_by_source_id.pop(order.source_id, None)
            raise

    async def _submit_once(self, order: OrderRequest) -> FillEvent:
        order_id = f"{PAPER_ORDER_ID_PREFIX}{next(self._order_ids)}"
        start_ms = self._now_ms()
        initial_continuity = self._book_continuity(order.token_id)
        jitter_offset_ms = self._sample_jitter_offset_ms()
        selected_latency_ms = latency_ms(
            self._config.paper_latency_ms,
            self._config.paper_latency_jitter_ms,
            jitter_offset_ms,
        )
        try:
            await self._sleep(selected_latency_ms / 1000)
        except ClockDataExhaustedError:
            current_continuity = self._book_continuity(order.token_id)
            if (
                initial_continuity is not None
                and initial_continuity.was_disrupted_by(current_continuity)
            ):
                return self._coverage_gap_rejection(order_id, order)
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=self._now_ms(),
                reject_reason=FillRejectReason.BACKTEST_DATA_EXHAUSTED,
                reject_message=BACKTEST_DATA_EXHAUSTED_MESSAGE,
            )
        current_continuity = self._book_continuity(order.token_id)
        if (
            initial_continuity is not None
            and initial_continuity.was_disrupted_by(current_continuity)
        ):
            return self._coverage_gap_rejection(order_id, order)
        if self._is_settled(order.condition_id):
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=self._now_ms(),
                reject_reason=FillRejectReason.MARKET_RESOLVED,
                reject_message=MARKET_RESOLVED_MESSAGE,
            )
        initial_book = await self._validated_book_input(
            order_id,
            order,
            start_ms=start_ms,
            selected_latency_ms=selected_latency_ms,
        )
        if isinstance(initial_book, FillEvent):
            return initial_book
        initial_market = await self._validated_market_data(
            order_id,
            order,
            initial_book,
        )
        if isinstance(initial_market, FillEvent):
            return initial_market

        # Re-read market metadata before the final book lookup. The final awaited
        # input is therefore the book snapshot that is immediately validated and
        # simulated, rather than a potentially slow metadata request.
        final_market = await self._validated_market_data(
            order_id,
            order,
            initial_book,
        )
        if isinstance(final_market, FillEvent):
            return final_market
        final_book = await self._validated_book_input(
            order_id,
            order,
            start_ms=start_ms,
            selected_latency_ms=selected_latency_ms,
        )
        if isinstance(final_book, FillEvent):
            return final_book
        final_market_reject = validate_fill_market_data(
            final_market,
            order,
            final_book.book,
        )
        if final_market_reject is not None:
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=final_book.fill_time_ms,
                reject_reason=final_market_reject[0],
                reject_message=final_market_reject[1],
            )
        fill = simulate_fill(
            order=order,
            book=final_book.book,
            fee_rate=final_market.fee_rate,
            max_slippage_pct=self._config.max_slippage_pct,
            order_id=order_id,
            fill_time_ms=final_book.fill_time_ms,
        )
        if fill is None:
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=final_book.fill_time_ms,
                reject_reason=FillRejectReason.NO_DEPTH_WITHIN_SLIPPAGE,
                reject_message=NO_DEPTH_WITHIN_SLIPPAGE_MESSAGE,
            )

        updated_position = self._portfolio.apply_fill(
            token_id=order.token_id,
            side=order.side,
            filled_size=fill.filled_size,
            average_price=fill.execution_price,
            fee_usdc=fill.fee_usdc,
        )
        if updated_position.size == 0:
            self._position_market_refs.pop(order.token_id, None)
        else:
            market_slug = order.market_slug or final_book.book.market_slug
            condition_id = order.condition_id or final_book.book.condition_id
            if market_slug and condition_id:
                self._position_market_refs[order.token_id] = (
                    market_slug,
                    condition_id,
                )
        return fill

    async def _validated_book_input(
        self,
        order_id: str,
        order: OrderRequest,
        *,
        start_ms: int,
        selected_latency_ms: int,
    ) -> _BookFillInput | FillEvent:
        """Read and validate one book at the execution-time boundary."""
        book = await latest_book(self._books, order.token_id)
        fill_time_ms = max(start_ms + selected_latency_ms, self._now_ms())
        if book is None:
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=FillRejectReason.BOOK_UNAVAILABLE,
                reject_message=BOOK_UNAVAILABLE_MESSAGE,
            )
        book_reject = classify_book(
            order,
            book,
            fill_time_ms,
            self._config.event_max_age_ms,
        )
        if book_reject is not None:
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=fill_time_ms,
                reject_reason=book_reject,
                reject_message=self._book_reject_message(book_reject),
            )
        return _BookFillInput(book=book, fill_time_ms=fill_time_ms)

    async def _validated_market_data(
        self,
        order_id: str,
        order: OrderRequest,
        book_input: _BookFillInput,
    ) -> FillMarketData | FillEvent:
        """Resolve and validate market metadata against an already-safe book."""
        market_data, market_reject = await resolve_fill_market_data(
            self._markets,
            order,
            book_input.book,
        )
        if market_reject is not None:
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=book_input.fill_time_ms,
                reject_reason=market_reject[0],
                reject_message=market_reject[1],
            )
        assert market_data is not None
        if self._is_settled(market_data.market.condition_id):
            return self._rejected_fill(
                order_id,
                order,
                received_at_ms=self._now_ms(),
                reject_reason=FillRejectReason.MARKET_RESOLVED,
                reject_message=MARKET_RESOLVED_MESSAGE,
            )
        return market_data

    def _is_settled(self, condition_id: str | None) -> bool:
        return condition_id is not None and condition_id in self._settled_conditions

    def _sample_jitter_offset_ms(self) -> int:
        jitter_ms = self._config.paper_latency_jitter_ms
        return 0 if jitter_ms == 0 else self._rng.randrange(jitter_ms + 1)

    def _book_continuity(self, token_id: str) -> BookContinuity | None:
        if self._continuity_source is None:
            return None
        return self._continuity_source.book_continuity(token_id)

    def _coverage_gap_rejection(
        self,
        order_id: str,
        order: OrderRequest,
    ) -> FillEvent:
        return self._rejected_fill(
            order_id,
            order,
            received_at_ms=self._now_ms(),
            reject_reason=FillRejectReason.BACKTEST_COVERAGE_GAP,
            reject_message=BACKTEST_COVERAGE_GAP_MESSAGE,
        )

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


def _complete_claim(future: asyncio.Future[FillEvent], fill: FillEvent) -> None:
    if not future.done():
        future.set_result(fill)
