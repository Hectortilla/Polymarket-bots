"""Dynamic market planning and loss-aware capture coordination."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from polymarket import PolymarketError

from polybot.framework.cadence import (
    RESOLUTION_RECONCILIATION_SECONDS,
    STREAM_PLAN_REFRESH_INTERVAL_SECONDS,
)
from polybot.framework.streams import StreamPlan
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.recording_feed import (
    CaptureContinuityError,
    MarketCapture,
    MarketRecordingFeed,
)
from polybot.polymarket.recording_metadata import (
    RecordingMarket,
    RecordingMarketResolver,
)
from polybot.polymarket.resolution import GAMMA_RECONCILIATION_SOURCE
from polybot.recording.clock import ObservationClock
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookDeltaPayload,
    CaptureAnomalyFragment,
    CaptureAnomalyPayload,
    CaptureBookDiagnostics,
    CaptureFragmentRole,
    CoverageGapPayload,
    CoverageGapReason,
    MarketIdentity,
    MarketMetadataPayload,
    RecordedBookLevel,
    RecordedEvent,
    ResolutionPayload,
)
from polybot.recording.planning import StreamPlanProvider
from polybot.recording.writer import (
    AsyncRecordingWriter,
    PendingRecordingEvent,
    RecordingCheckpointWrite,
    RecordingEventWrite,
)


CHECKPOINT_SECONDS = 60.0
MAX_PENDING_CAPTURE_EVENTS = 64


@dataclass(slots=True)
class _TrackedMarket:
    recording: RecordingMarket
    generation: int = 0
    capture: MarketCapture | None = None
    projector: BookDepthProjector | None = None
    pump: asyncio.Task[None] | None = None
    dropped_count: int = 0
    last_observed_at_ms: int = 0
    gap_ids: set[int] = field(default_factory=set)
    coverage_started: bool = False
    terminal_claimed: bool = False


@dataclass(frozen=True, slots=True)
class _CaptureStopped:
    condition_id: str
    generation: int
    reason: CoverageGapReason
    error: BaseException | None = None
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class _ResolutionStored:
    condition_id: str
    generation: int


@dataclass(slots=True)
class _PendingCaptureEvent:
    write: PendingRecordingEvent
    commit: asyncio.Task[RecordedEvent]
    coverage_ready: bool


type _ControlMessage = _CaptureStopped | _ResolutionStored


class RecordingCoordinator:
    """Keep dynamic plans captured without replacing existing subscriptions."""

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
        resumed_gap_condition_ids: dict[int, frozenset[str]] | None = None,
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
        self._max_pending_capture_events = max_pending_capture_events
        self._tracked: dict[str, _TrackedMarket] = {}
        self._condition_by_slug: dict[str, str] = {}
        self._plan_slugs: set[str] = set()
        self._retained_pending_slugs: set[str] = set()
        self._pending_slugs: set[str] = set()
        self._control: asyncio.Queue[_ControlMessage] = asyncio.Queue()
        self._record_lock = asyncio.Lock()
        self._next_generation = 1
        self._stopping = False
        self._terminal_metadata_pending: set[str] = set()
        self._resumed_gap_conditions = {
            gap_id: set(condition_ids)
            for gap_id, condition_ids in (
                {} if resumed_gap_condition_ids is None else resumed_gap_condition_ids
            ).items()
        }
        self._resumed_gap_affected_conditions = {
            gap_id: frozenset(condition_ids)
            for gap_id, condition_ids in self._resumed_gap_conditions.items()
        }

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
        except PolymarketError:
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
            _validate_revision(existing.recording, recording)
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

        tracked = _TrackedMarket(
            recording=recording,
        )
        self._tracked[condition_id] = tracked
        self._condition_by_slug[recording.market.slug] = condition_id
        if requested_slug is not None:
            self._condition_by_slug[requested_slug] = condition_id
        try:
            async with self._record_lock:
                observed_at_ms = self._clock.now_ms()
                await self._writer.record(
                    recording.metadata,
                    observed_at_ms=observed_at_ms,
                    source_timestamp_ms=None,
                    identity=_market_identity(recording.metadata),
                    subscription_generation=0,
                )
                tracked.last_observed_at_ms = max(
                    tracked.last_observed_at_ms,
                    observed_at_ms,
                )
            if recording.metadata.resolved:
                await self._record_gamma_resolution(tracked, recording)
            return
        except BaseException:
            self._tracked.pop(condition_id, None)
            for slug, mapped_condition in tuple(self._condition_by_slug.items()):
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
            except PolymarketError:
                continue
            tracked.generation = generation
            tracked.capture = capture
            tracked.projector = BookDepthProjector((tracked.recording.market,))
            tracked.dropped_count = capture.dropped_count
            tracked.pump = asyncio.create_task(self._pump(tracked, capture))

    async def _pump(
        self,
        tracked: _TrackedMarket,
        capture: MarketCapture,
    ) -> None:
        generation = capture.generation
        condition_id = tracked.recording.market.condition_id
        pending: deque[_PendingCaptureEvent] = deque()
        capture_read: asyncio.Task[CapturedMarketEvent] | None = asyncio.create_task(
            anext(capture)
        )
        stopped: _CaptureStopped | None = None
        resolution_queued = False
        capture_retired = False
        try:
            while capture_read is not None or pending:
                waiters: list[asyncio.Future | asyncio.Task] = []
                if capture_read is not None:
                    waiters.append(capture_read)
                if pending:
                    waiters.append(pending[0].commit)
                if not waiters:
                    raise AssertionError("capture pump has no pending work")
                done, _ = await asyncio.wait(
                    waiters,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if capture_read is not None and capture_read in done:
                    completed_read = capture_read
                    capture_read = None
                    try:
                        captured = completed_read.result()
                    except StopAsyncIteration:
                        stopped = _CaptureStopped(
                            condition_id,
                            generation,
                            CoverageGapReason.CAPTURE_ENDED,
                        )
                    except asyncio.CancelledError:
                        raise
                    except BaseException as error:
                        stopped = _CaptureStopped(
                            condition_id,
                            generation,
                            CoverageGapReason.CAPTURE_FAILURE,
                            error=error,
                        )
                    else:
                        dropped_count = capture.dropped_count
                        if dropped_count > tracked.dropped_count:
                            tracked.dropped_count = dropped_count
                            stopped = _CaptureStopped(
                                condition_id,
                                generation,
                                CoverageGapReason.SDK_HANDLE_DROP,
                            )
                        else:
                            try:
                                queued = self._enqueue_capture_event(
                                    tracked,
                                    capture,
                                    captured,
                                )
                            except BaseException as error:
                                stopped = _CaptureStopped(
                                    condition_id,
                                    generation,
                                    CoverageGapReason.RECORDING_WRITE_FAILURE,
                                    error=error,
                                    fatal=True,
                                )
                            else:
                                if queued is None:
                                    capture_retired = True
                                else:
                                    pending.append(queued)
                                    if isinstance(
                                        queued.write.event.payload,
                                        ResolutionPayload,
                                    ):
                                        resolution_queued = True

                while pending and pending[0].commit.done():
                    queued = pending.popleft()
                    try:
                        await self._commit_capture_event(tracked, queued)
                    except asyncio.CancelledError:
                        raise
                    except BaseException as error:
                        stopped = _CaptureStopped(
                            condition_id,
                            generation,
                            CoverageGapReason.RECORDING_WRITE_FAILURE,
                            error=error,
                            fatal=True,
                        )
                        break

                if stopped is not None and stopped.fatal:
                    await _cancel_task(capture_read)
                    capture_read = None
                    await _settle_pending_capture_events(pending)
                    pending.clear()
                    await self._control.put(stopped)
                    return

                if stopped is None and not resolution_queued:
                    dropped_count = capture.dropped_count
                    if dropped_count > tracked.dropped_count:
                        tracked.dropped_count = dropped_count
                        stopped = _CaptureStopped(
                            condition_id,
                            generation,
                            CoverageGapReason.SDK_HANDLE_DROP,
                        )

                if stopped is not None or resolution_queued or capture_retired:
                    await _cancel_task(capture_read)
                    capture_read = None
                elif (
                    capture_read is None
                    and len(pending) < self._max_pending_capture_events
                ):
                    capture_read = asyncio.create_task(anext(capture))

                if pending:
                    continue
                if resolution_queued:
                    await self._control.put(
                        _ResolutionStored(condition_id, generation)
                    )
                    return
                if capture_retired:
                    return
                if stopped is not None:
                    await self._control.put(stopped)
                    return
        except asyncio.CancelledError:
            await _cancel_task(capture_read)
            await _settle_pending_capture_events(pending)
            raise
        except BaseException as error:
            await _cancel_task(capture_read)
            await _settle_pending_capture_events(pending)
            await self._control.put(
                _CaptureStopped(
                    condition_id,
                    generation,
                    CoverageGapReason.CAPTURE_FAILURE,
                    error=error,
                )
            )

    def _enqueue_capture_event(
        self,
        tracked: _TrackedMarket,
        capture: MarketCapture,
        captured: CapturedMarketEvent,
    ) -> _PendingCaptureEvent | None:
        if (
            tracked.capture is not capture
            or tracked.terminal_claimed
            or self._stopping
        ):
            return None
        if isinstance(captured.payload, ResolutionPayload):
            tracked.terminal_claimed = True
        observed_at_ms = self._clock.now_ms()
        projector = tracked.projector
        if projector is None:
            raise AssertionError("active capture has no book projector")
        if isinstance(captured.payload, BookBaselinePayload):
            projector.apply_baseline(
                captured.payload,
                condition_id=tracked.recording.market.condition_id,
                received_at_ms=observed_at_ms,
            )
        elif isinstance(captured.payload, BookDeltaPayload):
            projector.apply_delta(
                captured.payload,
                condition_id=tracked.recording.market.condition_id,
                received_at_ms=observed_at_ms,
            )
        coverage_ready = set(tracked.recording.market.token_ids) <= (
            projector.baseline_token_ids
        )
        write = self._writer.enqueue_record(
            captured.payload,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=captured.source_timestamp_ms,
            identity=captured.identity,
            subscription_generation=capture.generation,
        )
        return _PendingCaptureEvent(
            write=write,
            commit=asyncio.create_task(write.wait()),
            coverage_ready=coverage_ready,
        )

    async def _commit_capture_event(
        self,
        tracked: _TrackedMarket,
        pending: _PendingCaptureEvent,
    ) -> None:
        event = await pending.commit
        tracked.last_observed_at_ms = max(
            tracked.last_observed_at_ms,
            event.observed_at_ms,
        )
        if pending.coverage_ready:
            await self._close_market_gaps(tracked, event.observed_at_ms)
            tracked.coverage_started = True
        elif isinstance(event.payload, ResolutionPayload):
            await self._close_market_gaps(tracked, event.observed_at_ms)

    async def _handle_control(self, message: _ControlMessage) -> None:
        tracked = self._tracked.get(message.condition_id)
        if tracked is None or tracked.generation != message.generation:
            return
        if isinstance(message, _ResolutionStored):
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
        tracked: _TrackedMarket,
        *,
        reason: CoverageGapReason,
        error: BaseException | None = None,
    ) -> None:
        if isinstance(error, CaptureContinuityError):
            await self._record_capture_anomaly(tracked, error)
        await self._close_capture(tracked)
        if tracked.coverage_started and not self._condition_has_gap(tracked):
            await self._open_gap(
                tracked,
                reason=reason,
                started_at_ms=tracked.last_observed_at_ms,
                details=(
                    None
                    if error is None
                    else f"{type(error).__name__}: {error}"
                ),
            )
        await self._ensure_captures()

    async def _record_capture_anomaly(
        self,
        tracked: _TrackedMarket,
        error: CaptureContinuityError,
    ) -> None:
        market = tracked.recording.market
        async with self._record_lock:
            await self._writer.record_anomaly(
                _capture_anomaly_payload(error),
                observed_at_ms=self._clock.now_ms(),
                identity=MarketIdentity(
                    condition_id=market.condition_id,
                    market_slug=market.slug,
                ),
                subscription_generation=tracked.generation,
            )

    async def _detect_drops(self) -> None:
        for tracked in tuple(self._tracked.values()):
            capture = tracked.capture
            if capture is None or tracked.terminal_claimed:
                continue
            dropped_count = capture.dropped_count
            if dropped_count <= tracked.dropped_count:
                continue
            tracked.dropped_count = dropped_count
            await self._restart_capture(
                tracked,
                reason=CoverageGapReason.SDK_HANDLE_DROP,
            )

    async def _open_gap(
        self,
        tracked: _TrackedMarket,
        *,
        reason: CoverageGapReason,
        started_at_ms: int,
        details: str | None = None,
    ) -> None:
        if tracked.gap_ids:
            return
        market = tracked.recording.market
        async with self._record_lock:
            gap = await self._writer.open_gap(
                CoverageGapPayload(
                    reason=reason,
                    started_at_ms=started_at_ms,
                    ended_at_ms=None,
                    affected_condition_ids=(market.condition_id,),
                    affected_market_slugs=(market.slug,),
                    affected_token_ids=market.token_ids,
                    details=details,
                ),
                observed_at_ms=self._clock.now_ms(),
                identity=MarketIdentity(
                    condition_id=market.condition_id,
                    market_slug=market.slug,
                ),
                subscription_generation=tracked.generation,
            )
            tracked.gap_ids.add(gap.gap_id)

    async def _write_checkpoints(self) -> None:
        async with self._record_lock:
            await self._write_checkpoint_batch(
                tuple(
                    tracked
                    for tracked in self._tracked.values()
                    if self._can_checkpoint(tracked)
                )
            )

    def _can_checkpoint(self, tracked: _TrackedMarket) -> bool:
        projector = tracked.projector
        return (
            tracked.capture is not None
            and projector is not None
            and set(tracked.recording.market.token_ids)
            <= projector.baseline_token_ids
            and not self._condition_has_open_gap(tracked)
            and not tracked.terminal_claimed
        )

    async def _write_checkpoint_batch(
        self,
        tracked_markets: tuple[_TrackedMarket, ...],
    ) -> None:
        if not tracked_markets:
            return
        observed_at_ms = self._clock.now_ms()
        writes = tuple(
            write
            for tracked in tracked_markets
            for write in self._checkpoint_writes(tracked, observed_at_ms)
        )
        if writes:
            await self._writer.checkpoint_batch(writes)

    def _checkpoint_writes(
        self,
        tracked: _TrackedMarket,
        observed_at_ms: int,
    ) -> tuple[RecordingCheckpointWrite, ...]:
        capture = tracked.capture
        projector = tracked.projector
        if capture is None or projector is None:
            raise AssertionError("checkpoint market has no active capture")
        return tuple(
            RecordingCheckpointWrite(
                book=BookBaselinePayload(
                    token_id=book.token_id,
                    bids=tuple(
                        RecordedBookLevel(level.price, level.size)
                        for level in book.bids
                    ),
                    asks=tuple(
                        RecordedBookLevel(level.price, level.size)
                        for level in book.asks
                    ),
                ),
                observed_at_ms=observed_at_ms,
                identity=MarketIdentity(
                    condition_id=book.condition_id,
                    market_slug=book.market_slug,
                    token_id=book.token_id,
                ),
                subscription_generation=capture.generation,
            )
            for book in projector.snapshots(received_at_ms=observed_at_ms)
        )

    async def _reconcile_resolutions(self) -> None:
        tracked = tuple(
            market
            for market in self._tracked.values()
            if (
                not market.terminal_claimed
                or market.recording.market.condition_id
                in self._terminal_metadata_pending
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
        except PolymarketError:
            return
        for current, recording in zip(tracked, refreshed, strict=True):
            if recording is None:
                continue
            _validate_revision(current.recording, recording)
            if current.terminal_claimed:
                if recording.metadata != current.recording.metadata:
                    await self._record_metadata(current, recording)
                if recording.metadata.resolved:
                    self._terminal_metadata_pending.discard(
                        current.recording.market.condition_id
                    )
                continue
            if recording.metadata.resolved:
                await self._record_gamma_resolution(current, recording)
                await self._close_capture(current)
            elif recording.metadata != current.recording.metadata:
                await self._record_metadata(current, recording)

    async def _reconcile_terminal_metadata(
        self,
        tracked: _TrackedMarket,
    ) -> None:
        condition_id = tracked.recording.market.condition_id
        try:
            (recording,) = await self._resolver.find_many(
                (tracked.recording.market.slug,)
            )
        except asyncio.CancelledError:
            raise
        except PolymarketError:
            self._terminal_metadata_pending.add(condition_id)
            return
        if recording is None:
            self._terminal_metadata_pending.add(condition_id)
            return
        _validate_revision(tracked.recording, recording)
        if recording.metadata != tracked.recording.metadata:
            await self._record_metadata(tracked, recording)
        if recording.metadata.resolved:
            self._terminal_metadata_pending.discard(condition_id)
        else:
            self._terminal_metadata_pending.add(condition_id)

    async def _record_metadata(
        self,
        tracked: _TrackedMarket,
        recording: RecordingMarket,
    ) -> None:
        _validate_revision(tracked.recording, recording)
        async with self._record_lock:
            observed_at_ms = self._clock.now_ms()
            await self._writer.record(
                recording.metadata,
                observed_at_ms=observed_at_ms,
                source_timestamp_ms=None,
                identity=_market_identity(recording.metadata),
                subscription_generation=tracked.generation,
            )
            tracked.recording = recording
            tracked.last_observed_at_ms = max(
                tracked.last_observed_at_ms,
                observed_at_ms,
            )

    async def _record_gamma_resolution(
        self,
        tracked: _TrackedMarket,
        recording: RecordingMarket,
    ) -> None:
        _validate_revision(tracked.recording, recording)
        market = recording.market
        if (
            not recording.metadata.resolved
            or market.winning_token_id is None
            or market.winning_outcome is None
        ):
            raise ValueError("resolved metadata does not identify a winner")
        async with self._record_lock:
            if tracked.terminal_claimed:
                return
            tracked.terminal_claimed = True
            observed_at_ms = self._clock.now_ms()
            writes: list[RecordingEventWrite] = []
            if recording.metadata != tracked.recording.metadata:
                writes.append(
                    RecordingEventWrite(
                        payload=recording.metadata,
                        observed_at_ms=observed_at_ms,
                        source_timestamp_ms=None,
                        identity=_market_identity(recording.metadata),
                        subscription_generation=tracked.generation,
                    )
                )
            writes.append(
                RecordingEventWrite(
                    payload=ResolutionPayload(
                        token_ids=market.token_ids,
                        winning_token_id=market.winning_token_id,
                        winning_outcome=market.winning_outcome,
                        source=GAMMA_RECONCILIATION_SOURCE,
                    ),
                    observed_at_ms=observed_at_ms,
                    source_timestamp_ms=None,
                    identity=MarketIdentity(
                        condition_id=market.condition_id,
                        market_slug=market.slug,
                    ),
                    subscription_generation=tracked.generation,
                ),
            )
            await self._writer.record_batch(tuple(writes))
            tracked.recording = recording
            tracked.last_observed_at_ms = max(
                tracked.last_observed_at_ms,
                observed_at_ms,
            )
            await self._close_market_gaps(tracked, observed_at_ms)

    async def _close_market_gaps(
        self,
        tracked: _TrackedMarket,
        ended_at_ms: int,
    ) -> None:
        checkpoint_condition_ids: set[str] = set()
        closed_condition_gap = bool(tracked.gap_ids)
        for gap_id in sorted(tracked.gap_ids):
            await self._writer.close_gap(gap_id, ended_at_ms=ended_at_ms)
        tracked.gap_ids.clear()
        condition_id = tracked.recording.market.condition_id
        for gap_id, remaining in tuple(self._resumed_gap_conditions.items()):
            if condition_id not in remaining:
                continue
            remaining.remove(condition_id)
            if remaining:
                continue
            await self._writer.close_gap(gap_id, ended_at_ms=ended_at_ms)
            self._resumed_gap_conditions.pop(gap_id, None)
            checkpoint_condition_ids.update(
                self._resumed_gap_affected_conditions.pop(gap_id)
            )

        if closed_condition_gap:
            checkpoint_condition_ids.add(condition_id)
        recovered_markets: list[_TrackedMarket] = []
        for recovered_condition_id in sorted(checkpoint_condition_ids):
            recovered = self._tracked.get(recovered_condition_id)
            if recovered is not None and self._can_checkpoint(recovered):
                recovered_markets.append(recovered)
        await self._write_checkpoint_batch(tuple(recovered_markets))

    def _condition_has_gap(self, tracked: _TrackedMarket) -> bool:
        condition_id = tracked.recording.market.condition_id
        return bool(tracked.gap_ids) or any(
            condition_id in remaining
            for remaining in self._resumed_gap_conditions.values()
        )

    def _condition_has_open_gap(self, tracked: _TrackedMarket) -> bool:
        condition_id = tracked.recording.market.condition_id
        return bool(tracked.gap_ids) or any(
            condition_id in self._resumed_gap_affected_conditions[gap_id]
            for gap_id in self._resumed_gap_conditions
        )

    async def _close_capture(self, tracked: _TrackedMarket) -> None:
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


def _market_identity(metadata: MarketMetadataPayload) -> MarketIdentity:
    return MarketIdentity(
        condition_id=metadata.condition_id,
        market_slug=metadata.market_slug,
    )


def _capture_anomaly_payload(
    error: CaptureContinuityError,
) -> CaptureAnomalyPayload:
    fragments = [
        _capture_anomaly_fragment(
            error.first_fragment,
            CaptureFragmentRole.INITIAL,
        )
    ]
    fragments.extend(
        _capture_anomaly_fragment(
            fragment,
            CaptureFragmentRole.MATCHING_CONTINUATION,
        )
        for fragment in error.matching_fragments
    )
    if error.mismatching_fragment is not None:
        fragments.append(
            _capture_anomaly_fragment(
                error.mismatching_fragment,
                CaptureFragmentRole.MISMATCHING_CONTINUATION,
            )
        )
    return CaptureAnomalyPayload(
        failure_kind=error.failure_kind,
        expected_fingerprint=error.expected_fingerprint,
        actual_fingerprint=error.actual_fingerprint,
        fragments=tuple(fragments),
        book_diagnostics=_capture_book_diagnostics(error),
        dropped_count_before=error.dropped_count_before,
        dropped_count_after=error.dropped_count_after,
        elapsed_ms=int(error.elapsed_seconds * 1_000),
        details=f"{type(error).__name__}: {error}",
    )


def _capture_anomaly_fragment(
    event: CapturedMarketEvent,
    role: CaptureFragmentRole,
) -> CaptureAnomalyFragment:
    return CaptureAnomalyFragment(
        role=role,
        source_timestamp_ms=event.source_timestamp_ms,
        identity=event.identity,
        payload=event.payload,
    )


def _capture_book_diagnostics(
    error: CaptureContinuityError,
) -> tuple[CaptureBookDiagnostics, ...]:
    projected = {
        book.token_id: (
            max((level.price for level in book.bids), default=None),
            min((level.price for level in book.asks), default=None),
        )
        for book in error.projected_books
    }
    advertised: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    for fragment in error.fragments:
        if not isinstance(fragment.payload, BookDeltaPayload):
            continue
        for change in fragment.payload.changes:
            best_bid, best_ask = advertised.get(change.token_id, (None, None))
            advertised[change.token_id] = (
                change.best_bid if change.best_bid is not None else best_bid,
                change.best_ask if change.best_ask is not None else best_ask,
            )
    return tuple(
        CaptureBookDiagnostics(
            token_id=token_id,
            projected_best_bid=projected.get(token_id, (None, None))[0],
            projected_best_ask=projected.get(token_id, (None, None))[1],
            advertised_best_bid=advertised.get(token_id, (None, None))[0],
            advertised_best_ask=advertised.get(token_id, (None, None))[1],
        )
        for token_id in sorted(projected.keys() | advertised.keys())
    )


async def _cancel_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _settle_pending_capture_events(
    pending: deque[_PendingCaptureEvent],
) -> None:
    if not pending:
        return
    await asyncio.gather(
        *(queued.commit for queued in pending),
        return_exceptions=True,
    )


def _validate_revision(
    current: RecordingMarket,
    refreshed: RecordingMarket,
) -> None:
    if (
        current.market.condition_id != refreshed.market.condition_id
        or current.market.slug != refreshed.market.slug
        or current.market.token_ids != refreshed.market.token_ids
        or tuple(outcome.label for outcome in current.market.outcomes)
        != tuple(outcome.label for outcome in refreshed.market.outcomes)
    ):
        raise ValueError("market metadata revision changed immutable identity")


def _advance_deadline(deadline: float, interval: float, now: float) -> float:
    while deadline <= now:
        deadline += interval
    return deadline
