"""Bounded capture-pump mechanics for one tracked recording market."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.recording_feed.capture import MarketCapture
from polybot.polymarket.stream_diagnostics import require_monotonic_dropped_count
from polybot.recording.clock import ObservationClock
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)
from polybot.recording.contracts.gaps import CoverageGapReason
from polybot.recording.contracts.records import RecordedEvent
from polybot.recording.contracts.payloads import ResolutionPayload
from polybot.recording.writer import AsyncRecordingWriter
from polybot.recording.writer_contracts import PendingRecordingEvent

from .state import CaptureStopped, ControlMessage, ResolutionStored, TrackedMarket


@dataclass(slots=True)
class PendingCaptureEvent:
    """A queued capture event paired with its durability acknowledgement."""

    write: PendingRecordingEvent
    commit: asyncio.Task[RecordedEvent]
    coverage_ready: bool


class CapturePump:
    """Drain one capture without outrunning durable archive acknowledgements."""

    def __init__(
        self,
        *,
        writer: AsyncRecordingWriter,
        clock: ObservationClock,
        control: asyncio.Queue[ControlMessage],
        max_pending_events: int,
        is_stopping: Callable[[], bool],
        on_event_committed: Callable[
            [TrackedMarket, PendingCaptureEvent], Awaitable[None]
        ],
    ) -> None:
        self._writer = writer
        self._clock = clock
        self._control = control
        self._max_pending_events = max_pending_events
        self._is_stopping = is_stopping
        self._on_event_committed = on_event_committed

    async def run(
        self,
        tracked: TrackedMarket,
        capture: MarketCapture,
    ) -> None:
        """Pump one capture until it terminates, resolves, or needs recovery."""
        generation = capture.generation
        condition_id = tracked.condition_id
        pending: deque[PendingCaptureEvent] = deque()
        capture_read: asyncio.Task[CapturedMarketEvent] | None = asyncio.create_task(
            anext(capture)
        )
        stopped: CaptureStopped | None = None
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
                        stopped = CaptureStopped(
                            condition_id,
                            generation,
                            CoverageGapReason.CAPTURE_ENDED,
                        )
                    except asyncio.CancelledError:
                        raise
                    except BaseException as error:
                        stopped = CaptureStopped(
                            condition_id,
                            generation,
                            CoverageGapReason.CAPTURE_FAILURE,
                            error=error,
                        )
                    else:
                        dropped_count = require_monotonic_dropped_count(
                            tracked.dropped_count,
                            capture.dropped_count,
                        )
                        if dropped_count > tracked.dropped_count:
                            tracked.dropped_count = dropped_count
                            stopped = CaptureStopped(
                                condition_id,
                                generation,
                                CoverageGapReason.SDK_HANDLE_DROP,
                            )
                        else:
                            try:
                                queued = self._enqueue_event(
                                    tracked,
                                    capture,
                                    captured,
                                )
                            except BaseException as error:
                                stopped = CaptureStopped(
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
                        await self._commit_event(tracked, queued)
                    except asyncio.CancelledError:
                        raise
                    except BaseException as error:
                        stopped = CaptureStopped(
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
                    await _settle_pending_events(pending)
                    pending.clear()
                    await self._control.put(stopped)
                    return

                if stopped is None and not resolution_queued:
                    dropped_count = require_monotonic_dropped_count(
                        tracked.dropped_count,
                        capture.dropped_count,
                    )
                    if dropped_count > tracked.dropped_count:
                        tracked.dropped_count = dropped_count
                        stopped = CaptureStopped(
                            condition_id,
                            generation,
                            CoverageGapReason.SDK_HANDLE_DROP,
                        )

                if stopped is not None or resolution_queued or capture_retired:
                    await _cancel_task(capture_read)
                    capture_read = None
                elif (
                    capture_read is None
                    and len(pending) < self._max_pending_events
                ):
                    capture_read = asyncio.create_task(anext(capture))

                if pending:
                    continue
                if resolution_queued:
                    await self._control.put(
                        ResolutionStored(condition_id, generation)
                    )
                    return
                if capture_retired:
                    return
                if stopped is not None:
                    await self._control.put(stopped)
                    return
        except asyncio.CancelledError:
            await _cancel_task(capture_read)
            await _settle_pending_events(pending)
            raise
        except BaseException as error:
            await _cancel_task(capture_read)
            await _settle_pending_events(pending)
            await self._control.put(
                CaptureStopped(
                    condition_id,
                    generation,
                    CoverageGapReason.CAPTURE_FAILURE,
                    error=error,
                )
            )

    def _enqueue_event(
        self,
        tracked: TrackedMarket,
        capture: MarketCapture,
        captured: CapturedMarketEvent,
    ) -> PendingCaptureEvent | None:
        if (
            tracked.capture is not capture
            or tracked.terminal_claimed
            or self._is_stopping()
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
                condition_id=tracked.condition_id,
                received_at_ms=observed_at_ms,
            )
        elif isinstance(captured.payload, BookDeltaPayload):
            projector.apply_delta(
                captured.payload,
                condition_id=tracked.condition_id,
                received_at_ms=observed_at_ms,
            )
        coverage_ready = projector.has_complete_baseline(tracked.condition_id)
        write = self._writer.enqueue_record(
            captured.payload,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=captured.source_timestamp_ms,
            identity=captured.identity,
            subscription_generation=capture.generation,
        )
        return PendingCaptureEvent(
            write=write,
            commit=asyncio.create_task(write.wait()),
            coverage_ready=coverage_ready,
        )

    async def _commit_event(
        self,
        tracked: TrackedMarket,
        pending: PendingCaptureEvent,
    ) -> None:
        event = await pending.commit
        tracked.last_observed_at_ms = max(
            tracked.last_observed_at_ms,
            event.observed_at_ms,
        )
        await self._on_event_committed(tracked, pending)


async def _cancel_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _settle_pending_events(
    pending: deque[PendingCaptureEvent],
) -> None:
    if not pending:
        return
    await asyncio.gather(
        *(queued.commit for queued in pending),
        return_exceptions=True,
    )
