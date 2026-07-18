"""Fail-open performance recording for ordinary paper runs."""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Callable

from polybot.cli.observability.events import (
    DispatchCompleted,
    MarketSettled,
    PortfolioBookBootstrap,
    RuntimeEvent,
    RuntimeFailed,
    StreamReceived,
)
from polybot.cli.streams.contracts import StreamKind
from polybot.execution.broker import Broker
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.framework.clock import Clock
from polybot.framework.config.models import BotConfig
from polybot.framework.events import FillEvent, OrderRequest
from polybot.framework.events.books import BookSnapshot

from .artifacts import PerformanceArtifacts
from .contracts import PerformanceRunStatus


class PaperPerformanceWarning(RuntimeWarning):
    """Visible warning emitted when optional paper artifacts fail."""


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
        self._last_timestamp_ms = artifacts.selection.start_ms
        self._prior_books_by_event: dict[int, BookSnapshot | None] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        self._record(lambda: self._artifacts.start(self._now_ms(), self._portfolio))
        if self._enabled:
            self._sampler = asyncio.create_task(self._sample_intervals())

    def emit(self, event: RuntimeEvent) -> None:
        if isinstance(event, RuntimeFailed):
            self._status = PerformanceRunStatus.FAILED
            self._failure = event.error
            return
        if isinstance(event, StreamReceived):
            def record_stream() -> None:
                timestamp_ms = self._now_ms()
                self._artifacts.advance_to(timestamp_ms, self._portfolio)
                self._artifacts.record_events()
                if event.item.kind is StreamKind.BOOK:
                    self._prior_books_by_event[id(event.item)] = self._artifacts.books.get(
                        event.item.event.token_id
                    )
                    self._artifacts.record_book(event.item.event)

            self._record(record_stream)
            return
        if isinstance(event, PortfolioBookBootstrap):
            def record_bootstrap() -> None:
                self._artifacts.advance_to(self._now_ms(), self._portfolio)
                self._artifacts.record_book(event.book)

            self._record(record_bootstrap)
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

            self._record(record_dispatch)
            return
        if isinstance(event, MarketSettled):
            def record_settlement() -> None:
                self._artifacts.record_settlement(
                    timestamp_ms=self._now_ms(),
                    portfolio=self._portfolio,
                )
                self._artifacts.remove_books(event.settlement.resolution.token_ids)

            self._record(record_settlement)

    def record_fill(
        self,
        *,
        submitted_at_ms: int,
        order: OrderRequest,
        fill: FillEvent,
    ) -> None:
        self._record(
            lambda: self._artifacts.record_fill(
                submitted_at_ms=submitted_at_ms,
                order=order,
                fill=fill,
                portfolio=self._portfolio,
            )
        )

    def mark_cancelled(self) -> None:
        self._status = PerformanceRunStatus.CANCELLED

    async def stop(self) -> None:
        if self._sampler is not None:
            self._sampler.cancel()
            await asyncio.gather(self._sampler, return_exceptions=True)
            self._sampler = None
        if not self._artifacts.started or self._artifacts.finalized:
            return
        status = self._status
        error = self._failure
        if not self._enabled:
            status = PerformanceRunStatus.FAILED
            error = error or "optional paper performance recording failed"
        try:
            self._artifacts.finalize(
                status=status,
                ended_at_ms=self._now_ms(),
                portfolio=self._portfolio,
                error=error if status is PerformanceRunStatus.FAILED else None,
            )
        except Exception as finalization_error:
            warnings.warn(
                "paper performance artifact finalization failed: "
                f"{type(finalization_error).__name__}: {finalization_error}",
                PaperPerformanceWarning,
                stacklevel=2,
            )

    async def _sample_intervals(self) -> None:
        interval_seconds = self._artifacts.report_interval_ms / 1_000
        while self._enabled:
            await self._clock.sleep(interval_seconds)
            self._record(
                lambda: self._artifacts.advance_to(self._now_ms(), self._portfolio)
            )

    def _record(self, operation: Callable[[], object]) -> None:
        if not self._enabled:
            return
        try:
            operation()
        except Exception as error:
            self._enabled = False
            self._status = PerformanceRunStatus.FAILED
            self._failure = f"{type(error).__name__}: {error}"
            warnings.warn(
                f"paper performance recording disabled: {self._failure}",
                PaperPerformanceWarning,
                stacklevel=3,
            )

    def _now_ms(self) -> int:
        timestamp_ms = max(self._last_timestamp_ms, self._clock.now_ms())
        self._last_timestamp_ms = timestamp_ms
        return timestamp_ms


class PaperPerformanceObserver:
    def __init__(self, recorder: PaperPerformanceRecorder) -> None:
        self._recorder = recorder

    async def start(self, config: BotConfig) -> None:
        del config
        await self._recorder.start()

    def emit(self, event: RuntimeEvent) -> None:
        self._recorder.emit(event)

    async def stop(self) -> None:
        await self._recorder.stop()


class PaperPerformanceBroker(Broker):
    def __init__(
        self,
        broker: Broker,
        *,
        recorder: PaperPerformanceRecorder,
        clock: Clock,
    ) -> None:
        self._broker = broker
        self._recorder = recorder
        self._clock = clock

    async def submit(self, order: OrderRequest) -> FillEvent:
        submitted_at_ms = self._clock.now_ms()
        fill = await self._broker.submit(order)
        self._recorder.record_fill(
            submitted_at_ms=submitted_at_ms,
            order=order,
            fill=fill,
        )
        return fill

    async def cancel_all(self) -> None:
        await self._broker.cancel_all()
