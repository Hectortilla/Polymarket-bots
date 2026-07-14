"""Stream-health projection for the runner orchestration loop."""

from __future__ import annotations

from time import time

from polybot.cli.observability.events import StreamHealth
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason

from ..streams.contracts import BookStreamEvent, StreamEvent
from ..streams.telemetry import StreamTelemetry


def stream_health(
    event: StreamEvent,
    outcome: DispatchOutcome,
    telemetry: StreamTelemetry,
) -> StreamHealth:
    lag_ms = None
    stale = False
    if isinstance(event, BookStreamEvent):
        lag_ms = max(0, int(time() * 1000) - event.event.received_at_ms)
        stale = (
            not outcome.accepted
            and outcome.skip_reason is DispatchSkipReason.BOOK_STALE
        )
    return StreamHealth(
        queue_depth=telemetry.queue_depth,
        peak_queue_depth=telemetry.peak_queue_depth,
        book_dispatch_lag_ms=lag_ms,
        book_stale=stale,
        book_received_count=telemetry.book_received_count,
        book_dropped_count=telemetry.book_dropped_count,
    )
