"""Capture-continuity diagnostics serialized into recording anomalies."""

from __future__ import annotations

from decimal import Decimal

from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.recording_feed.continuity import CaptureContinuityError
from polybot.recording.contracts.book import BookDeltaPayload
from polybot.recording.contracts.anomalies import (
    CaptureAnomalyFragment,
    CaptureAnomalyPayload,
    CaptureBookDiagnostics,
    CaptureFragmentRole,
)


def create_capture_anomaly_payload(
    error: CaptureContinuityError,
) -> CaptureAnomalyPayload:
    """Normalize one capture continuity failure for the durable journal."""
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
