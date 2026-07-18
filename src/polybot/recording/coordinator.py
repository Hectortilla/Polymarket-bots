"""Dynamic market planning and loss-aware capture coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field

from polymarket import PolymarketError

from polybot.framework.events.resolutions import GAMMA_RECONCILIATION_SOURCE
from polybot.framework.streams import StreamPlan
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.recording_feed import MarketCapture, MarketRecordingFeed
from polybot.polymarket.recording_metadata import (
    RecordingMarket,
    RecordingMarketResolver,
)
from polybot.recording.clock import ObservationClock
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookDeltaPayload,
    CoverageGapPayload,
    MarketIdentity,
    MarketMetadataPayload,
    RecordedBookLevel,
    ResolutionPayload,
)
from polybot.recording.planning import StreamPlanProvider
from polybot.recording.writer import AsyncRecordingWriter


PLAN_REFRESH_SECONDS = 1.0
CHECKPOINT_SECONDS = 60.0
RESOLUTION_RECONCILIATION_SECONDS = 30.0


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
    reason: str
    error: BaseException | None = None
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class _ResolutionStored:
    condition_id: str
    generation: int


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
        plan_refresh_seconds: float = PLAN_REFRESH_SECONDS,
        checkpoint_seconds: float = CHECKPOINT_SECONDS,
        resolution_reconciliation_seconds: float = (
            RESOLUTION_RECONCILIATION_SECONDS
        ),
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
                await self._record_metadata(existing, recording, flush=True)
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
                    flush=True,
                )
                tracked.last_observed_at_ms = observed_at_ms
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
        try:
            async for captured in capture:
                dropped_count = capture.dropped_count
                if dropped_count > tracked.dropped_count:
                    tracked.dropped_count = dropped_count
                    await self._control.put(
                        _CaptureStopped(
                            tracked.recording.market.condition_id,
                            generation,
                            "sdk_handle_drop",
                        )
                    )
                    return
                try:
                    resolution_stored = await self._record_capture_event(
                        tracked,
                        capture,
                        captured,
                    )
                except asyncio.CancelledError:
                    raise
                except BaseException as error:
                    await self._control.put(
                        _CaptureStopped(
                            tracked.recording.market.condition_id,
                            generation,
                            "recording_write_failure",
                            error=error,
                            fatal=True,
                        )
                    )
                    return
                if resolution_stored:
                    await self._control.put(
                        _ResolutionStored(
                            tracked.recording.market.condition_id,
                            generation,
                        )
                    )
                    return
                dropped_count = capture.dropped_count
                if dropped_count > tracked.dropped_count:
                    tracked.dropped_count = dropped_count
                    await self._control.put(
                        _CaptureStopped(
                            tracked.recording.market.condition_id,
                            generation,
                            "sdk_handle_drop",
                        )
                    )
                    return
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await self._control.put(
                _CaptureStopped(
                    tracked.recording.market.condition_id,
                    generation,
                    "capture_failure",
                    error=error,
                )
            )
            return
        await self._control.put(
            _CaptureStopped(
                tracked.recording.market.condition_id,
                generation,
                "capture_ended",
            )
        )

    async def _record_capture_event(
        self,
        tracked: _TrackedMarket,
        capture: MarketCapture,
        captured: CapturedMarketEvent,
    ) -> bool:
        async with self._record_lock:
            if (
                tracked.capture is not capture
                or tracked.terminal_claimed
                or self._stopping
            ):
                return False
            is_resolution = isinstance(captured.payload, ResolutionPayload)
            if is_resolution:
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
            await self._writer.record(
                captured.payload,
                observed_at_ms=observed_at_ms,
                source_timestamp_ms=captured.source_timestamp_ms,
                identity=captured.identity,
                subscription_generation=capture.generation,
                flush=is_resolution,
            )
            tracked.last_observed_at_ms = observed_at_ms
            ready = set(tracked.recording.market.token_ids) <= (
                projector.baseline_token_ids
            )
            if ready:
                await self._close_market_gaps(tracked, observed_at_ms)
                tracked.coverage_started = True
            elif is_resolution:
                await self._close_market_gaps(tracked, observed_at_ms)
            return is_resolution

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
        reason: str,
        error: BaseException | None = None,
    ) -> None:
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

    async def _detect_drops(self) -> None:
        for tracked in tuple(self._tracked.values()):
            capture = tracked.capture
            if capture is None or tracked.terminal_claimed:
                continue
            dropped_count = capture.dropped_count
            if dropped_count <= tracked.dropped_count:
                continue
            tracked.dropped_count = dropped_count
            await self._restart_capture(tracked, reason="sdk_handle_drop")

    async def _open_gap(
        self,
        tracked: _TrackedMarket,
        *,
        reason: str,
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
            observed_at_ms = self._clock.now_ms()
            for tracked in tuple(self._tracked.values()):
                capture = tracked.capture
                projector = tracked.projector
                if (
                    capture is None
                    or projector is None
                    or not set(tracked.recording.market.token_ids)
                    <= projector.baseline_token_ids
                    or self._condition_has_gap(tracked)
                    or tracked.terminal_claimed
                ):
                    continue
                for book in projector.snapshots(received_at_ms=observed_at_ms):
                    await self._writer.checkpoint(
                        BookBaselinePayload(
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
                    await self._record_metadata(current, recording, flush=True)
                if recording.metadata.resolved:
                    self._terminal_metadata_pending.discard(
                        current.recording.market.condition_id
                    )
                continue
            if recording.metadata.resolved:
                await self._record_gamma_resolution(current, recording)
                await self._close_capture(current)
            elif recording.metadata != current.recording.metadata:
                await self._record_metadata(current, recording, flush=False)

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
            await self._record_metadata(tracked, recording, flush=True)
        if recording.metadata.resolved:
            self._terminal_metadata_pending.discard(condition_id)
        else:
            self._terminal_metadata_pending.add(condition_id)

    async def _record_metadata(
        self,
        tracked: _TrackedMarket,
        recording: RecordingMarket,
        *,
        flush: bool,
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
                flush=flush,
            )
            tracked.recording = recording
            tracked.last_observed_at_ms = observed_at_ms

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
            if recording.metadata != tracked.recording.metadata:
                await self._writer.record(
                    recording.metadata,
                    observed_at_ms=observed_at_ms,
                    source_timestamp_ms=None,
                    identity=_market_identity(recording.metadata),
                    subscription_generation=tracked.generation,
                )
            await self._writer.record(
                ResolutionPayload(
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
                flush=True,
            )
            tracked.recording = recording
            tracked.last_observed_at_ms = observed_at_ms
            await self._close_market_gaps(tracked, observed_at_ms)

    async def _close_market_gaps(
        self,
        tracked: _TrackedMarket,
        ended_at_ms: int,
    ) -> None:
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

    def _condition_has_gap(self, tracked: _TrackedMarket) -> bool:
        condition_id = tracked.recording.market.condition_id
        return bool(tracked.gap_ids) or any(
            condition_id in remaining
            for remaining in self._resumed_gap_conditions.values()
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
