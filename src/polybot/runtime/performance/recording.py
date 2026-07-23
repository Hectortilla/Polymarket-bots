"""Fail-open paper-performance event recording for a runtime."""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Callable

from polybot.async_io import run_blocking
from polybot.cli.observability.events import (
    DispatchCompleted,
    MarketSettled,
    PortfolioBookBootstrap,
    RuntimeEvent,
    RuntimeFailed,
    StreamReceived,
)
from polybot.cli.streams.contracts import StreamKind
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.framework.clock import Clock
from polybot.framework.events import FillEvent, OrderRequest
from polybot.framework.events.books import BookSnapshot
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.contracts.run import PerformanceRunStatus

from .warnings import PaperPerformanceWarning


PAPER_ARTIFACT_QUEUE_CAPACITY = 1_024
PAPER_RECORDING_DISABLED_MESSAGE = "paper performance recording disabled"
PAPER_FINALIZATION_FAILED_MESSAGE = "paper performance artifact finalization failed"


class PaperPerformanceRecorder:
    """Coordinate one optional paper artifact writer without risking trading."""

    def __init__(
        self,
        artifacts: PerformanceArtifacts,
        *,
        portfolio: PaperPortfolio,
        clock: Clock,
    ) -> None:
        self._artifacts = artifacts
        self._portfolio = portfolio
        self._clock = clock
        self._enabled = True
        self._failure: str | None = None
        self._status = PerformanceRunStatus.COMPLETED
        self._sampler: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._operations: asyncio.Queue[Callable[[], object] | None] = asyncio.Queue(
            maxsize=PAPER_ARTIFACT_QUEUE_CAPACITY
        )
        self._last_timestamp_ms = artifacts.selection.start_ms
        self._prior_books_by_event: dict[int, BookSnapshot | None] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        portfolio = self._portfolio_copy()
        try:
            await run_blocking(
                self._artifacts.start,
                self._now_ms(),
                portfolio,
            )
        except Exception as error:
            self._disable(error, stacklevel=2)
        if self._enabled:
            self._worker = asyncio.create_task(self._run_operations())
            self._sampler = asyncio.create_task(self._sample_intervals())

    def emit(self, event: RuntimeEvent) -> None:
        if isinstance(event, RuntimeFailed):
            self._status = PerformanceRunStatus.FAILED
            self._failure = event.error
            return
        if isinstance(event, StreamReceived):
            timestamp_ms = self._now_ms()
            portfolio = self._portfolio_copy()

            def record_stream() -> None:
                self._artifacts.advance_to(timestamp_ms, portfolio)
                self._artifacts.record_events()
                if event.item.kind is StreamKind.BOOK:
                    self._prior_books_by_event[id(event.item)] = self._artifacts.books.get(
                        event.item.event.token_id
                    )
                    self._artifacts.record_book(event.item.event)

            self._enqueue(record_stream)
            return
        if isinstance(event, PortfolioBookBootstrap):
            timestamp_ms = self._now_ms()
            portfolio = self._portfolio_copy()

            def record_bootstrap() -> None:
                self._artifacts.advance_to(timestamp_ms, portfolio)
                self._artifacts.record_book(event.book)

            self._enqueue(record_bootstrap)
            return
        if isinstance(event, DispatchCompleted):
            accepted = None if event.outcome is None else event.outcome.accepted

            def record_dispatch() -> None:
                self._artifacts.record_dispatch(accepted)
                if event.item.kind is not StreamKind.BOOK:
                    return
                previous = self._prior_books_by_event.pop(id(event.item), None)
                if accepted is not False:
                    return
                token_id = event.item.event.token_id
                if previous is None:
                    self._artifacts.remove_books((token_id,))
                else:
                    self._artifacts.record_book(previous)

            self._enqueue(record_dispatch)
            return
        if isinstance(event, MarketSettled):
            timestamp_ms = self._now_ms()
            portfolio = self._portfolio_copy()

            def record_settlement() -> None:
                self._artifacts.record_settlement(
                    timestamp_ms=timestamp_ms,
                    portfolio=portfolio,
                )
                self._artifacts.remove_books(event.settlement.resolution.token_ids)

            self._enqueue(record_settlement)

    def record_fill(
        self,
        *,
        submitted_at_ms: int,
        order: OrderRequest,
        fill: FillEvent,
    ) -> None:
        portfolio = self._portfolio_copy()
        self._enqueue(
            lambda: self._artifacts.record_fill(
                submitted_at_ms=submitted_at_ms,
                order=order,
                fill=fill,
                portfolio=portfolio,
            )
        )

    def mark_cancelled(self) -> None:
        self._status = PerformanceRunStatus.CANCELLED

    async def stop(self) -> None:
        if self._sampler is not None:
            self._sampler.cancel()
            await asyncio.gather(self._sampler, return_exceptions=True)
            self._sampler = None
        if self._worker is not None:
            await self._operations.join()
            await self._operations.put(None)
            await self._worker
            self._worker = None
        if not self._artifacts.started or self._artifacts.finalized:
            return
        status = self._status
        error = self._failure
        if not self._enabled:
            status = PerformanceRunStatus.FAILED
            error = error or "optional paper performance recording failed"
        try:
            await run_blocking(
                self._artifacts.finalize,
                status=status,
                ended_at_ms=self._now_ms(),
                portfolio=self._portfolio_copy(),
                error=error if status is PerformanceRunStatus.FAILED else None,
            )
        except Exception as finalization_error:
            warnings.warn(
                f"{PAPER_FINALIZATION_FAILED_MESSAGE}: "
                f"{type(finalization_error).__name__}: {finalization_error}",
                PaperPerformanceWarning,
                stacklevel=2,
            )

    async def _sample_intervals(self) -> None:
        interval_seconds = self._artifacts.report_interval_ms / 1_000
        while self._enabled:
            await self._clock.sleep(interval_seconds)
            portfolio = self._portfolio_copy()
            timestamp_ms = self._now_ms()
            self._enqueue(
                lambda timestamp_ms=timestamp_ms, portfolio=portfolio: (
                    self._artifacts.advance_to(timestamp_ms, portfolio)
                )
            )

    def _enqueue(self, operation: Callable[[], object]) -> None:
        if not self._enabled:
            return
        try:
            self._operations.put_nowait(operation)
        except asyncio.QueueFull as error:
            self._disable(error, stacklevel=3)

    async def _run_operations(self) -> None:
        while True:
            operation = await self._operations.get()
            try:
                if operation is None:
                    return
                if self._enabled:
                    await run_blocking(operation)
            except Exception as error:
                self._disable(error, stacklevel=2)
            finally:
                self._operations.task_done()

    def _disable(self, error: BaseException, *, stacklevel: int) -> None:
        if not self._enabled:
            return
        self._enabled = False
        self._status = PerformanceRunStatus.FAILED
        self._failure = f"{type(error).__name__}: {error}"
        warnings.warn(
            f"{PAPER_RECORDING_DISABLED_MESSAGE}: {self._failure}",
            PaperPerformanceWarning,
            stacklevel=stacklevel,
        )

    def _portfolio_copy(self) -> PaperPortfolio:
        cash, fees, positions = self._portfolio.snapshot()
        return PaperPortfolio(cash, fees, positions)

    def _now_ms(self) -> int:
        timestamp_ms = max(self._last_timestamp_ms, self._clock.now_ms())
        self._last_timestamp_ms = timestamp_ms
        return timestamp_ms
