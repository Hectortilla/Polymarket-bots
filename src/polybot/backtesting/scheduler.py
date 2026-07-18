"""Deterministic event scheduling and live-equivalent replay coalescing."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.framework.base import BaseBot
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
)
from polybot.framework.runner import BotRunner
from polybot.framework.streams import STREAM_PLAN_REFRESH_INTERVAL_MS
from polybot.performance.artifacts import PerformanceArtifacts
from polybot.performance.contracts import SampleReason
from polybot.recording.contracts import RecordedEvent


class ReplayCursor:
    def __init__(self, events: Iterator[RecordedEvent], *, after_sequence: int = 0) -> None:
        self._events = events
        self._after_sequence = after_sequence
        self._next: RecordedEvent | None = None
        self._finished = False

    def peek(self) -> RecordedEvent | None:
        if self._next is None and not self._finished:
            for event in self._events:
                if event.sequence > self._after_sequence:
                    self._next = event
                    break
            else:
                self._finished = True
        return self._next

    def pop(self) -> RecordedEvent | None:
        event = self.peek()
        self._next = None
        return event


@dataclass(frozen=True, slots=True)
class _BookMarker:
    token_id: str


@dataclass(frozen=True, slots=True)
class _ResolutionMarker:
    event: MarketResolutionEvent


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
    ) -> None:
        self._bot = bot
        self._runner = runner
        self._paper_broker = paper_broker
        self._state = state
        self._clock = clock
        self._cursor = cursor
        self._artifacts = artifacts
        self._admitted_slugs: set[str] = set()
        self._terminal_slugs: set[str] = set()
        self._pending_markers: deque[PendingMarker] = deque()
        self._pending_books: dict[str, BookSnapshot] = {}
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
        try:
            await self._bot.on_start(self._runner.ctx)
            new_slugs = await self._refresh_admissions()
            self._enqueue_bootstraps(new_slugs)
            await self._drain_pending()
            while (event := self._cursor.peek()) is not None:
                await self._advance_idle_to(event.observed_at_ms)
                current = self._cursor.pop()
                if current is None:
                    break
                await self._apply_event(current, queue_only=False)
                await self._drain_pending()
            await self._advance_idle_to(self._clock.end_at_ms)
            await self._refresh_end_boundary()
            await self._drain_pending()
        finally:
            await self._bot.on_stop(self._runner.ctx)

    async def _advance_idle_to(self, target_ms: int) -> None:
        if target_ms < self._clock.now_ms():
            raise BacktestError(
                BacktestFailureReason.INVALID_SELECTION,
                "recorded observation time moved backwards during replay",
            )
        while self._next_plan_refresh_ms < target_ms:
            self._move_to(self._next_plan_refresh_ms)
            self._next_plan_refresh_ms += STREAM_PLAN_REFRESH_INTERVAL_MS
            new_slugs = await self._refresh_admissions()
            self._enqueue_bootstraps(new_slugs)
            await self._drain_pending()
        self._move_to(target_ms)

    async def _advance_during_callback(self, target_ms: int) -> None:
        if target_ms < self._clock.now_ms():
            raise ValueError("simulated callback latency cannot move backwards")
        while True:
            event = self._cursor.peek()
            event_time = None if event is None else event.observed_at_ms
            next_time = min(
                target_ms,
                self._next_plan_refresh_ms,
                target_ms if event_time is None else event_time,
            )
            if next_time > self._clock.now_ms():
                self._move_to(next_time)
            handled = False
            if (
                event_time is not None
                and event_time <= target_ms
                and event_time <= self._next_plan_refresh_ms
            ):
                current = self._cursor.pop()
                if current is not None:
                    await self._apply_event(current, queue_only=True)
                    handled = True
            if self._next_plan_refresh_ms <= target_ms and (
                event_time is None or self._next_plan_refresh_ms < event_time
            ):
                self._move_to(self._next_plan_refresh_ms)
                self._next_plan_refresh_ms += STREAM_PLAN_REFRESH_INTERVAL_MS
                self._plan_refresh_due = True
                handled = True
            if not handled:
                break
        self._move_to(target_ms)

    async def _refresh_end_boundary(self) -> None:
        if self._next_plan_refresh_ms != self._clock.end_at_ms:
            return
        self._next_plan_refresh_ms += STREAM_PLAN_REFRESH_INTERVAL_MS
        new_slugs = await self._refresh_admissions()
        self._enqueue_bootstraps(new_slugs)

    async def _apply_event(self, event: RecordedEvent, *, queue_only: bool) -> None:
        self.event_count += 1
        self._artifacts.counters.record_events()
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
        resolution_was_queued = (
            applied.resolution is not None
            and applied.resolution.market_slug in admitted_before
        )
        if resolution_was_queued and applied.resolution is not None:
            self._pending_markers.append(_ResolutionMarker(applied.resolution))
        if not queue_only:
            new_slugs = await self._refresh_admissions()
            self._enqueue_bootstraps(new_slugs)
        if (
            applied.resolution is not None
            and not resolution_was_queued
            and applied.resolution.market_slug in self._admitted_slugs
        ):
            self._pending_markers.append(_ResolutionMarker(applied.resolution))

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

    def _enqueue_bootstraps(self, new_slugs: set[str]) -> set[str]:
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
        if book.token_id in self._pending_books:
            self._pending_books[book.token_id] = book
            return
        self._pending_books[book.token_id] = book
        self._pending_markers.append(_BookMarker(book.token_id))

    async def _drain_pending(self) -> None:
        while self._pending_markers:
            marker = self._pending_markers.popleft()
            if isinstance(marker, _BookMarker):
                book = self._pending_books.pop(marker.token_id)
                self._remember_outcome(await self._runner.dispatch_book(book))
            else:
                await self._settle(marker.event)
            if self._plan_refresh_due:
                new_slugs = await self._refresh_admissions()
                self._enqueue_bootstraps(new_slugs)

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
        self._artifacts.record_transaction(
            self._clock.now_ms(),
            SampleReason.SETTLEMENT,
            self._paper_broker.portfolio,
        )
        self._artifacts.remove_books(event.token_ids)
        await self._runner.dispatch_market_resolution(settlement.resolution)

    def _remember_outcome(self, outcome: DispatchOutcome) -> None:
        self._artifacts.counters.record_dispatch(outcome.accepted)
        if outcome.accepted:
            self.accepted_dispatch_count += 1
        else:
            self.skipped_dispatch_count += 1

    def _move_to(self, target_ms: int) -> None:
        if target_ms > self._clock.now_ms():
            self._artifacts.advance_to(target_ms, self._paper_broker.portfolio)
        self._clock.move_to(target_ms)


def _next_interval(now_ms: int, interval_ms: int) -> int:
    return ((now_ms // interval_ms) + 1) * interval_ms
