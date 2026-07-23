"""Replay orchestration over archive state, bot callbacks, and paper execution."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from polybot.async_io import run_blocking
from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.backtesting.coverage import ReplayCoverage
from polybot.backtesting.scheduler.cursor import ReplayCursor
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.framework.base import BaseBot
from polybot.framework.cadence import STREAM_PLAN_REFRESH_INTERVAL_MS
from polybot.framework.coalescing import PendingByKey
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
)
from polybot.framework.runner import BotRunner
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.contracts.run import SampleReason
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.records import RecordedEvent


@dataclass(frozen=True, slots=True)
class _BookMarker:
    token_id: str


@dataclass(frozen=True, slots=True)
class _ResolutionMarker:
    event: MarketResolutionEvent


@dataclass(frozen=True, slots=True)
class _ReplayEventMutation:
    resolution: MarketResolutionEvent | None
    resolution_was_queued: bool


PendingMarker = _BookMarker | _ResolutionMarker


class ReplayScheduler:
    def __init__(
        self,
        *,
        bot: BaseBot,
        runner: BotRunner,
        paper_broker: PaperBroker,
        state: ArchiveMarketState,
        clock: ReplayClock,
        cursor: ReplayCursor,
        artifacts: PerformanceArtifacts,
        coverage: ReplayCoverage | None = None,
    ) -> None:
        self._bot = bot
        self._runner = runner
        self._paper_broker = paper_broker
        self._state = state
        self._clock = clock
        self._cursor = cursor
        self._artifacts = artifacts
        self._coverage = coverage
        self._admitted_slugs: set[str] = set()
        self._terminal_slugs: set[str] = set()
        self._pending_markers: deque[PendingMarker] = deque()
        self._pending_books: PendingByKey[str, BookSnapshot] = PendingByKey()
        self._settled_conditions: set[str] = set()
        self._plan_refresh_due = False
        self._next_plan_refresh_ms = _next_interval(
            clock.now_ms(), STREAM_PLAN_REFRESH_INTERVAL_MS
        )
        self.event_count = 0
        self.accepted_dispatch_count = 0
        self.skipped_dispatch_count = 0
        self.resolution_count = 0
        clock.set_advance_driver(self._advance_during_callback)

    async def run(self) -> None:
        fast_forwarded = False
        try:
            self._activate_blackouts_through(self._clock.now_ms())
            await self._bot.on_start(self._runner.ctx)
            new_slugs = await self._refresh_admissions()
            await self._enqueue_bootstraps(new_slugs)
            await self._drain_pending()
            while (event := await self._cursor.peek()) is not None:
                if self._can_fast_forward():
                    await self._fast_forward_to_end()
                    fast_forwarded = True
                    break
                await self._advance_idle_to(event.observed_at_ms)
                current = await self._cursor.pop()
                if current is None:
                    break
                await self._apply_regular_event(current)
                await self._drain_pending()
            if not fast_forwarded:
                await self._advance_idle_to(self._clock.end_at_ms)
                await self._refresh_end_boundary()
            await self._drain_pending()
        finally:
            await self._cursor.aclose()
            await self._bot.on_stop(self._runner.ctx)

    async def _advance_idle_to(self, target_ms: int) -> None:
        if target_ms < self._clock.now_ms():
            raise BacktestError(
                BacktestFailureReason.INVALID_SELECTION,
                "recorded observation time moved backwards during replay",
            )
        while self._next_plan_refresh_ms < target_ms:
            await self._move_to(self._next_plan_refresh_ms)
            self._next_plan_refresh_ms += STREAM_PLAN_REFRESH_INTERVAL_MS
            new_slugs = await self._refresh_admissions()
            await self._enqueue_bootstraps(new_slugs)
            await self._drain_pending()
        await self._move_to(target_ms)

    async def _advance_during_callback(self, target_ms: int) -> None:
        if target_ms < self._clock.now_ms():
            raise ValueError("simulated callback latency cannot move backwards")
        while True:
            event = await self._cursor.peek()
            event_time = None if event is None else event.observed_at_ms
            next_time = min(
                target_ms,
                self._next_plan_refresh_ms,
                target_ms if event_time is None else event_time,
            )
            if next_time > self._clock.now_ms():
                await self._move_to(next_time)
            handled = False
            if (
                event_time is not None
                and event_time <= target_ms
                and event_time <= self._next_plan_refresh_ms
            ):
                current = await self._cursor.pop()
                if current is not None:
                    self._apply_callback_latency_event(current)
                    handled = True
            if self._next_plan_refresh_ms <= target_ms and (
                event_time is None or self._next_plan_refresh_ms < event_time
            ):
                await self._move_to(self._next_plan_refresh_ms)
                self._next_plan_refresh_ms += STREAM_PLAN_REFRESH_INTERVAL_MS
                self._plan_refresh_due = True
                handled = True
            if not handled:
                break
        await self._move_to(target_ms)

    async def _refresh_end_boundary(self) -> None:
        if self._next_plan_refresh_ms != self._clock.end_at_ms:
            return
        self._next_plan_refresh_ms += STREAM_PLAN_REFRESH_INTERVAL_MS
        new_slugs = await self._refresh_admissions()
        await self._enqueue_bootstraps(new_slugs)

    async def _apply_regular_event(self, event: RecordedEvent) -> None:
        mutation = self._apply_event_mutation(event)
        if mutation is None:
            return
        new_slugs = await self._refresh_admissions()
        await self._enqueue_bootstraps(new_slugs)
        self._enqueue_newly_admitted_resolution(mutation)

    def _apply_callback_latency_event(self, event: RecordedEvent) -> None:
        """Apply an event while a strategy callback owns plan refresh timing."""
        self._apply_event_mutation(event)

    def _apply_event_mutation(
        self,
        event: RecordedEvent,
    ) -> _ReplayEventMutation | None:
        self.event_count += 1
        self._artifacts.record_events()
        if isinstance(event.payload, CoverageGapPayload):
            return None
        applied = self._state.apply(event)
        for book in applied.books:
            self._artifacts.record_book(book)
        admitted_before = self._admitted_slugs.copy()
        self._enqueue_books(
            tuple(
                book
                for book in applied.books
                if book.market_slug in admitted_before
            )
        )
        resolution = applied.resolution
        resolution_was_queued = (
            resolution is not None and resolution.market_slug in admitted_before
        )
        if resolution_was_queued and resolution is not None:
            self._pending_markers.append(_ResolutionMarker(resolution))
        return _ReplayEventMutation(
            resolution=resolution,
            resolution_was_queued=resolution_was_queued,
        )

    def _enqueue_newly_admitted_resolution(
        self,
        mutation: _ReplayEventMutation,
    ) -> None:
        resolution = mutation.resolution
        if (
            resolution is not None
            and not mutation.resolution_was_queued
            and resolution.market_slug in self._admitted_slugs
        ):
            self._pending_markers.append(_ResolutionMarker(resolution))

    async def _refresh_admissions(self) -> set[str]:
        admitted: set[str] = set()
        while True:
            self._plan_refresh_due = False
            plan = await self._runner.refresh_stream_plan()
            rules = (*plan.current, *plan.next)
            if any(rule.wallet_addresses for rule in rules):
                raise BacktestError(
                    BacktestFailureReason.UNSUPPORTED_INPUT,
                    "wallet stream rules cannot be replayed from a market-only archive",
                )
            current_slugs = set(plan.current_market_slugs)
            if current_slugs:
                missing_metadata = sorted(
                    slug
                    for slug in current_slugs
                    if self._state.market_for_slug(slug) is None
                )
                if missing_metadata:
                    raise BacktestError(
                        BacktestFailureReason.MISSING_MARKET_DATA,
                        "current bot markets are absent from the selected recording: "
                        + ", ".join(missing_metadata),
                    )
                missing_books = sorted(
                    slug
                    for slug in current_slugs
                    if slug not in self._admitted_slugs
                    and not self._state.has_complete_book(slug)
                    and not self._state.is_blacked_out(slug)
                )
                if missing_books:
                    raise BacktestError(
                        BacktestFailureReason.MISSING_MARKET_DATA,
                        "current bot markets lack a complete two-token book: "
                        + ", ".join(missing_books),
                    )
                candidates = current_slugs
            else:
                candidates = set(self._state.market_slugs)
            candidates.difference_update(self._terminal_slugs)
            new_slugs = candidates.difference(self._admitted_slugs)
            admitted.update(new_slugs)
            self._admitted_slugs.update(new_slugs)
            self._runner.set_runtime_market_slugs(
                frozenset(self._admitted_slugs.difference(self._terminal_slugs))
            )
            if not self._plan_refresh_due:
                return admitted

    async def _enqueue_bootstraps(self, new_slugs: set[str]) -> set[str]:
        if not new_slugs:
            return set()
        bootstraps = self._state.bootstrap_books(
            new_slugs,
            received_at_ms=self._clock.now_ms(),
        )
        for book in bootstraps:
            self._artifacts.record_book(book)
        self._enqueue_books(bootstraps)
        return {book.token_id for book in bootstraps}

    def _enqueue_books(self, books: tuple[BookSnapshot, ...]) -> None:
        for book in books:
            self._enqueue_book(book)

    def _enqueue_book(self, book: BookSnapshot) -> None:
        if not self._pending_books.update(book.token_id, book):
            return
        self._pending_markers.append(_BookMarker(book.token_id))

    async def _drain_pending(self) -> None:
        while self._pending_markers:
            marker = self._pending_markers.popleft()
            if isinstance(marker, _BookMarker):
                book = self._pending_books.pop(marker.token_id)
                await self._remember_outcome(await self._runner.dispatch_book(book))
            else:
                await self._settle(marker.event)
            if self._plan_refresh_due:
                new_slugs = await self._refresh_admissions()
                await self._enqueue_bootstraps(new_slugs)

    async def _settle(self, event: MarketResolutionEvent) -> None:
        if event.condition_id in self._settled_conditions:
            return
        paper_positions = self._paper_broker.settle_market(event)
        settlement = MarketSettlementEvent(
            resolution=event,
            paper_positions=paper_positions,
            followed_wallet_positions=(),
            settled_at_ms=self._clock.now_ms(),
        )
        self._settled_conditions.add(event.condition_id)
        self._terminal_slugs.add(event.market_slug)
        self._admitted_slugs.discard(event.market_slug)
        self._runner.set_runtime_market_slugs(
            frozenset(self._admitted_slugs.difference(self._terminal_slugs))
        )
        self.resolution_count += 1
        self._artifacts.counters.record_resolutions()
        await run_blocking(
            self._artifacts.record_transaction,
            self._clock.now_ms(),
            SampleReason.SETTLEMENT,
            self._paper_broker.portfolio,
        )
        self._artifacts.remove_books(event.token_ids)
        await self._runner.dispatch_market_resolution(settlement.resolution)

    async def _remember_outcome(self, outcome: DispatchOutcome) -> None:
        self._artifacts.counters.record_dispatch(outcome.accepted)
        if outcome.accepted:
            self.accepted_dispatch_count += 1
        else:
            self.skipped_dispatch_count += 1

    async def _move_to(self, target_ms: int) -> None:
        if target_ms < self._clock.now_ms():
            raise ValueError("replay time cannot move backwards")
        while (
            self._coverage is not None
            and (boundary_ms := self._coverage.next_boundary_at_ms) is not None
            and boundary_ms <= target_ms
        ):
            if boundary_ms > self._clock.now_ms():
                await run_blocking(
                    self._artifacts.advance_to,
                    boundary_ms - 1,
                    self._paper_broker.portfolio,
                )
                self._clock.move_to(boundary_ms)
            self._activate_blackouts_through(boundary_ms)
            self._release_blackouts_through(boundary_ms)
            await run_blocking(
                self._artifacts.advance_to,
                boundary_ms,
                self._paper_broker.portfolio,
            )
        await self._move_clock_to(target_ms)

    async def _move_clock_to(self, target_ms: int) -> None:
        if target_ms > self._clock.now_ms():
            await run_blocking(
                self._artifacts.advance_to,
                target_ms,
                self._paper_broker.portfolio,
            )
        self._clock.move_to(target_ms)

    def _activate_blackouts_through(self, boundary_ms: int) -> None:
        if self._coverage is None:
            return
        records = self._coverage.pop_start_records_through(boundary_ms)
        if not records:
            return
        invalidated_token_ids: set[str] = set()
        for record in records:
            invalidated_token_ids.update(self._state.begin_blackout(record))
        if not invalidated_token_ids:
            return
        affected_positions = invalidated_token_ids.intersection(
            self._paper_broker.portfolio.positions
        )
        self._artifacts.record_coverage_gap_affected_positions(
            affected_positions
        )
        invalidated = tuple(sorted(invalidated_token_ids))
        self._artifacts.remove_books(invalidated)
        for token_id in invalidated:
            self._pending_books.discard(token_id)
        self._pending_markers = deque(
            marker
            for marker in self._pending_markers
            if not (
                isinstance(marker, _BookMarker)
                and marker.token_id in invalidated_token_ids
            )
        )

    def _release_blackouts_through(self, boundary_ms: int) -> None:
        if self._coverage is None:
            return
        if not self._coverage.pop_end_records_through(boundary_ms):
            return
        books = self._state.recover_books_at(boundary_ms)
        for book in books:
            self._artifacts.record_book(book)
        self._enqueue_books(
            tuple(
                book
                for book in books
                if book.market_slug in self._admitted_slugs
            )
        )

    def _can_fast_forward(self) -> bool:
        return (
            (self._coverage is None or self._coverage.next_boundary_at_ms is None)
            and not self._paper_broker.portfolio.positions
            and self._bot.backtest_is_quiescent(self._runner.ctx)
        )

    async def _fast_forward_to_end(self) -> None:
        """Advance a flat, explicitly finished strategy without replaying I/O."""
        await self._move_to(self._clock.end_at_ms)


def _next_interval(now_ms: int, interval_ms: int) -> int:
    return ((now_ms // interval_ms) + 1) * interval_ms
