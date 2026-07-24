"""Dynamic market planning and loss-aware recording coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from polybot.framework.cadence import (
    RESOLUTION_RECONCILIATION_SECONDS,
    STREAM_PLAN_REFRESH_INTERVAL_SECONDS,
)
from polybot.framework.streams import StreamPlan
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import MarketDataTransportError
from polybot.polymarket.recording_feed.continuity import CaptureContinuityError
from polybot.polymarket.recording_feed.feed import MarketRecordingFeed
from polybot.polymarket.stream_diagnostics import require_monotonic_dropped_count
from polybot.polymarket.recording_metadata.contracts import RecordingMarket
from polybot.polymarket.recording_metadata.resolver import RecordingMarketResolver
from polybot.recording.clock import ObservationClock
from polybot.recording.contracts.gaps import CoverageGapReason
from polybot.recording.contracts.payloads import ResolutionPayload
from polybot.recording.planning import StreamPlanProvider
from polybot.recording.writer import AsyncRecordingWriter

from .capture import CapturePump, PendingCaptureEvent
from .persistence import RecordingPersistence
from .state import (
    CaptureStopped,
    ControlMessage,
    ReleasedResumedGap,
    ResolutionStored,
    ResumedGapRecovery,
    TrackedMarket,
)


CHECKPOINT_SECONDS = 60.0
MAX_PENDING_CAPTURE_EVENTS = 64


class RecordingCoordinator:
    """Keep a dynamic market plan captured without replacing subscriptions."""

    def __init__(
        self,
        *,
        provider: StreamPlanProvider,
        resolver: RecordingMarketResolver,
        feed: MarketRecordingFeed,
        writer: AsyncRecordingWriter,
        clock: ObservationClock,
        stop_when_terminal: bool,
        plan_refresh_seconds: float = STREAM_PLAN_REFRESH_INTERVAL_SECONDS,
        checkpoint_seconds: float = CHECKPOINT_SECONDS,
        resolution_reconciliation_seconds: float = (
            RESOLUTION_RECONCILIATION_SECONDS
        ),
        max_pending_capture_events: int = MAX_PENDING_CAPTURE_EVENTS,
        resumed_gap_conditions_by_id: dict[int, frozenset[str]] | None = None,
    ) -> None:
        for value, name in (
            (plan_refresh_seconds, "plan refresh interval"),
            (checkpoint_seconds, "checkpoint interval"),
            (
                resolution_reconciliation_seconds,
                "resolution reconciliation interval",
            ),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if max_pending_capture_events <= 0:
            raise ValueError("pending capture event limit must be positive")
        self._provider = provider
        self._resolver = resolver
        self._feed = feed
        self._writer = writer
        self._clock = clock
        self._stop_when_terminal = stop_when_terminal
        self._plan_refresh_seconds = plan_refresh_seconds
        self._checkpoint_seconds = checkpoint_seconds
        self._resolution_reconciliation_seconds = (
            resolution_reconciliation_seconds
        )
        self._tracked: dict[str, TrackedMarket] = {}
        self._condition_by_slug: dict[str, str] = {}
        self._plan_slugs: set[str] = set()
        self._retained_pending_slugs: set[str] = set()
        self._pending_slugs: set[str] = set()
        self._control: asyncio.Queue[ControlMessage] = asyncio.Queue()
        self._record_lock = asyncio.Lock()
        self._persistence = RecordingPersistence(
            writer,
            clock,
            self._record_lock,
        )
        self._next_generation = 1
        self._stopping = False
        self._terminal_metadata_pending: set[str] = set()
        self._gap_recovery = ResumedGapRecovery(
            resumed_gap_conditions_by_id
        )
        self._capture_pump = CapturePump(
            writer=writer,
            clock=clock,
            control=self._control,
            max_pending_events=max_pending_capture_events,
            is_stopping=lambda: self._stopping,
            on_event_committed=self._commit_capture_event,
        )

    @property
    def tracked_condition_ids(self) -> frozenset[str]:
        return frozenset(self._tracked)

    @property
    def pending_slugs(self) -> frozenset[str]:
        return frozenset(self._pending_slugs)

    @property
    def terminal(self) -> bool:
        if not self._stop_when_terminal or self._pending_slugs:
            return False
        if not self._plan_slugs:
            return False
        return all(
            (condition_id := self._condition_by_slug.get(slug)) is not None
            and self._tracked[condition_id].terminal_claimed
            and self._tracked[condition_id].capture is None
            and condition_id not in self._terminal_metadata_pending
            for slug in self._plan_slugs
        )

    async def start(
        self,
        plan: StreamPlan,
        markets: Iterable[RecordingMarket],
        *,
        retained_missing_slugs: Iterable[str] = (),
    ) -> None:
        """Seed the first plan, resolve delayed slugs, and start captures."""
        self._set_plan(plan)
        self._retained_pending_slugs = {
            slug.strip() for slug in retained_missing_slugs if slug.strip()
        }
        for recording in markets:
            await self._add_market(recording)
        self._rebuild_pending_slugs()
        await self._resolve_pending_slugs()
        await self._ensure_captures()

    async def run(self, shutdown: asyncio.Event) -> None:
        """Refresh the plan and capture integrity until shutdown or terminal state."""
        if self.terminal:
            return
        loop = asyncio.get_running_loop()
        next_plan = loop.time() + self._plan_refresh_seconds
        next_checkpoint = loop.time() + self._checkpoint_seconds
        next_resolution = loop.time() + self._resolution_reconciliation_seconds
        control = asyncio.create_task(self._control.get())
        stopped = asyncio.create_task(shutdown.wait())
        try:
            while True:
                self._raise_writer_failure()
                now = loop.time()
                timeout = max(
                    0.0,
                    min(next_plan, next_checkpoint, next_resolution) - now,
                )
                done, _ = await asyncio.wait(
                    (control, stopped),
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                self._raise_writer_failure()
                if control in done:
                    message = control.result()
                    control = asyncio.create_task(self._control.get())
                    await self._handle_control(message)
                    if self.terminal:
                        return
                if stopped in done:
                    return

                now = loop.time()
                if now >= next_plan:
                    await self._refresh_plan()
                    await self._detect_drops()
                    await self._ensure_captures()
                    next_plan = _advance_deadline(
                        next_plan,
                        self._plan_refresh_seconds,
                        now,
                    )
                    if self.terminal:
                        return
                if now >= next_checkpoint:
                    await self._detect_drops()
                    await self._ensure_captures()
                    await self._write_checkpoints()
                    next_checkpoint = _advance_deadline(
                        next_checkpoint,
                        self._checkpoint_seconds,
                        now,
                    )
                if now >= next_resolution:
                    await self._reconcile_resolutions()
                    next_resolution = _advance_deadline(
                        next_resolution,
                        self._resolution_reconciliation_seconds,
                        now,
                    )
                    if self.terminal:
                        return
        finally:
            self._stopping = True
            control.cancel()
            stopped.cancel()
            await asyncio.gather(control, stopped, return_exceptions=True)
            await self._close_all_captures()

    async def close(self) -> None:
        """Stop all active capture handles and drain their tasks."""
        self._stopping = True
        await self._close_all_captures()

    async def _refresh_plan(self) -> None:
        plan = await self._provider.plan(self._clock.now_ms())
        self._set_plan(plan)
        self._rebuild_pending_slugs()
        await self._resolve_pending_slugs()

    def _set_plan(self, plan: StreamPlan) -> None:
        self._plan_slugs = set(
            (*plan.current_market_slugs, *plan.next_market_slugs)
        )

    def _rebuild_pending_slugs(self) -> None:
        wanted = self._plan_slugs | self._retained_pending_slugs
        self._pending_slugs.intersection_update(wanted)
        self._pending_slugs.update(
            slug for slug in wanted if slug not in self._condition_by_slug
        )

    async def _resolve_pending_slugs(self) -> None:
        if not self._pending_slugs:
            return
        slugs = tuple(sorted(self._pending_slugs))
        try:
            resolved = await self._resolver.find_many(slugs)
        except asyncio.CancelledError:
            raise
        except MarketDataTransportError:
            return
        for requested_slug, recording in zip(slugs, resolved, strict=True):
            if recording is None:
                continue
            await self._add_market(recording, requested_slug=requested_slug)
            self._pending_slugs.discard(requested_slug)
            self._retained_pending_slugs.discard(requested_slug)

    async def _add_market(
        self,
        recording: RecordingMarket,
        *,
        requested_slug: str | None = None,
    ) -> None:
        condition_id = recording.market.condition_id
        existing = self._tracked.get(condition_id)
        if existing is not None:
            existing.recording.assert_compatible_revision(recording)
            self._condition_by_slug[recording.market.slug] = condition_id
            if requested_slug is not None:
                self._condition_by_slug[requested_slug] = condition_id
            if recording.metadata.resolved and not existing.terminal_claimed:
                await self._record_gamma_resolution(existing, recording)
                await self._close_capture(existing)
            elif (
                recording.metadata != existing.recording.metadata
                and (not existing.terminal_claimed or recording.metadata.resolved)
            ):
                await self._record_metadata(existing, recording)
            return

        tracked = TrackedMarket(recording=recording)
        self._tracked[condition_id] = tracked
        self._condition_by_slug[recording.market.slug] = condition_id
        if requested_slug is not None:
            self._condition_by_slug[requested_slug] = condition_id
        try:
            await self._persistence.record_initial_metadata(tracked)
            if recording.metadata.resolved:
                await self._record_gamma_resolution(tracked, recording)
            return
        except BaseException:
            self._tracked.pop(condition_id, None)
            for slug, mapped_condition in tuple(
                self._condition_by_slug.items()
            ):
                if mapped_condition == condition_id:
                    self._condition_by_slug.pop(slug, None)
            raise

    async def _ensure_captures(self) -> None:
        for tracked in tuple(self._tracked.values()):
            if tracked.terminal_claimed or tracked.capture is not None:
                continue
            generation = self._next_generation
            self._next_generation += 1
            try:
                capture = await self._feed.open_capture(
                    tracked.recording.market,
                    generation=generation,
                )
            except asyncio.CancelledError:
                raise
            except MarketDataTransportError:
                continue
            tracked.generation = generation
            tracked.capture = capture
            tracked.projector = BookDepthProjector((tracked.recording.market,))
            tracked.dropped_count = capture.dropped_count
            tracked.pump = asyncio.create_task(
                self._capture_pump.run(tracked, capture)
            )

    async def _commit_capture_event(
        self,
        tracked: TrackedMarket,
        pending: PendingCaptureEvent,
    ) -> None:
        event = pending.write.event
        if pending.coverage_ready:
            await self._close_market_gaps(tracked, event.observed_at_ms)
            tracked.coverage_started = True
        elif isinstance(event.payload, ResolutionPayload):
            await self._close_market_gaps(tracked, event.observed_at_ms)

    async def _handle_control(self, message: ControlMessage) -> None:
        tracked = self._tracked.get(message.condition_id)
        if tracked is None or tracked.generation != message.generation:
            return
        if isinstance(message, ResolutionStored):
            await self._reconcile_terminal_metadata(tracked)
            await self._close_capture(tracked)
            return
        if message.fatal:
            if message.error is None:
                raise RuntimeError("recording writer failed")
            raise message.error
        if tracked.terminal_claimed or self._stopping:
            await self._close_capture(tracked)
            return
        await self._restart_capture(
            tracked,
            reason=message.reason,
            error=message.error,
        )

    async def _restart_capture(
        self,
        tracked: TrackedMarket,
        *,
        reason: CoverageGapReason,
        error: BaseException | None = None,
    ) -> None:
        if isinstance(error, CaptureContinuityError):
            await self._persistence.record_capture_anomaly(tracked, error)
        await self._close_capture(tracked)
        if (
            tracked.coverage_started
            and not self._condition_needs_gap_recovery(tracked)
        ):
            await self._persistence.open_gap(
                tracked,
                reason=reason,
                started_at_ms=tracked.last_observed_at_ms,
                details=(
                    None if error is None else f"{type(error).__name__}: {error}"
                ),
            )
        await self._ensure_captures()

    async def _detect_drops(self) -> None:
        for tracked in tuple(self._tracked.values()):
            capture = tracked.capture
            if capture is None or tracked.terminal_claimed:
                continue
            dropped_count = require_monotonic_dropped_count(
                tracked.dropped_count,
                capture.dropped_count,
            )
            if dropped_count == tracked.dropped_count:
                continue
            tracked.dropped_count = dropped_count
            await self._restart_capture(
                tracked,
                reason=CoverageGapReason.SDK_HANDLE_DROP,
            )

    async def _write_checkpoints(self) -> None:
        await self._persistence.write_checkpoint_batch(
            tuple(
                tracked
                for tracked in self._tracked.values()
                if self._can_checkpoint(tracked)
            )
        )

    def _can_checkpoint(self, tracked: TrackedMarket) -> bool:
        projector = tracked.projector
        return (
            tracked.capture is not None
            and projector is not None
            and projector.has_complete_baseline(tracked.condition_id)
            and not self._condition_is_in_open_gap_scope(tracked)
            and not tracked.terminal_claimed
        )

    async def _reconcile_resolutions(self) -> None:
        tracked = tuple(
            market
            for market in self._tracked.values()
            if (
                not market.terminal_claimed
                or market.condition_id in self._terminal_metadata_pending
            )
        )
        if not tracked:
            return
        try:
            refreshed = await self._resolver.find_many(
                market.recording.market.slug for market in tracked
            )
        except asyncio.CancelledError:
            raise
        except MarketDataTransportError:
            return
        for current, recording in zip(tracked, refreshed, strict=True):
            if recording is None:
                continue
            current.recording.assert_compatible_revision(recording)
            if current.terminal_claimed:
                if recording.metadata != current.recording.metadata:
                    await self._record_metadata(current, recording)
                if recording.metadata.resolved:
                    self._terminal_metadata_pending.discard(current.condition_id)
                continue
            if recording.metadata.resolved:
                await self._record_gamma_resolution(current, recording)
                await self._close_capture(current)
            elif recording.metadata != current.recording.metadata:
                await self._record_metadata(current, recording)

    async def _reconcile_terminal_metadata(
        self,
        tracked: TrackedMarket,
    ) -> None:
        condition_id = tracked.condition_id
        try:
            (recording,) = await self._resolver.find_many(
                (tracked.recording.market.slug,)
            )
        except asyncio.CancelledError:
            raise
        except MarketDataTransportError:
            self._terminal_metadata_pending.add(condition_id)
            return
        if recording is None:
            self._terminal_metadata_pending.add(condition_id)
            return
        tracked.recording.assert_compatible_revision(recording)
        if recording.metadata != tracked.recording.metadata:
            await self._record_metadata(tracked, recording)
        if recording.metadata.resolved:
            self._terminal_metadata_pending.discard(condition_id)
        else:
            self._terminal_metadata_pending.add(condition_id)

    async def _record_metadata(
        self,
        tracked: TrackedMarket,
        recording: RecordingMarket,
    ) -> None:
        await self._persistence.record_metadata(tracked, recording)

    async def _record_gamma_resolution(
        self,
        tracked: TrackedMarket,
        recording: RecordingMarket,
    ) -> None:
        observed_at_ms = await self._persistence.record_gamma_resolution(
            tracked,
            recording,
        )
        if observed_at_ms is not None:
            await self._close_market_gaps(tracked, observed_at_ms)

    async def _close_market_gaps(
        self,
        tracked: TrackedMarket,
        ended_at_ms: int,
    ) -> None:
        checkpoint_condition_ids: set[str] = set()
        closed_condition_gap = bool(tracked.gap_ids)
        own_gap_ids = tuple(sorted(tracked.gap_ids))
        await self._persistence.close_gaps(
            own_gap_ids,
            ended_at_ms=ended_at_ms,
        )
        tracked.gap_ids.clear()
        for released in self._gap_recovery.release_condition(tracked.condition_id):
            await self._close_released_gap(released, ended_at_ms)
            checkpoint_condition_ids.update(released.affected_condition_ids)

        if closed_condition_gap:
            checkpoint_condition_ids.add(tracked.condition_id)
        recovered_markets = tuple(
            recovered
            for condition_id in sorted(checkpoint_condition_ids)
            if (recovered := self._tracked.get(condition_id)) is not None
            and self._can_checkpoint(recovered)
        )
        await self._persistence.write_checkpoint_batch(recovered_markets)

    async def _close_released_gap(
        self,
        released: ReleasedResumedGap,
        ended_at_ms: int,
    ) -> None:
        try:
            await self._persistence.close_gaps(
                (released.gap_id,),
                ended_at_ms=ended_at_ms,
            )
        except BaseException:
            self._gap_recovery.restore_release(released)
            raise
        self._gap_recovery.close_released_gap(released)

    def _condition_needs_gap_recovery(self, tracked: TrackedMarket) -> bool:
        return self._gap_recovery.needs_recovery(
            tracked.condition_id,
            tracked.gap_ids,
        )

    def _condition_is_in_open_gap_scope(self, tracked: TrackedMarket) -> bool:
        return self._gap_recovery.is_in_open_scope(
            tracked.condition_id,
            tracked.gap_ids,
        )

    async def _close_capture(self, tracked: TrackedMarket) -> None:
        async with self._record_lock:
            capture = tracked.capture
            pump = tracked.pump
            tracked.capture = None
            tracked.pump = None
        if capture is not None:
            await capture.close()
        if pump is not None and pump is not asyncio.current_task():
            if not pump.done():
                pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)

    async def _close_all_captures(self) -> None:
        for tracked in tuple(self._tracked.values()):
            try:
                await self._close_capture(tracked)
            except Exception:
                pass

    def _raise_writer_failure(self) -> None:
        failure = self._writer.failure
        if failure is not None:
            raise RuntimeError("recording writer failed") from failure


def _advance_deadline(deadline: float, interval: float, now: float) -> float:
    while deadline <= now:
        deadline += interval
    return deadline
