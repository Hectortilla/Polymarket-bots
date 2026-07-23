"""Continuity evidence for split market-book revisions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.recording.contracts.book import BookDeltaPayload
from polybot.recording.contracts.anomalies import (
    CaptureFailureKind,
    RevisionFingerprint,
)


class CaptureContinuityError(MarketDataError):
    """A quarantined split revision whose continuity could not be proven."""

    def __init__(
        self,
        crossed_error: MarketDataError,
        *,
        failure_kind: CaptureFailureKind,
        first_fragment: CapturedMarketEvent,
        matching_fragments: tuple[CapturedMarketEvent, ...],
        mismatching_fragment: CapturedMarketEvent | None,
        expected_fingerprint: RevisionFingerprint | None,
        actual_fingerprint: RevisionFingerprint | None,
        projected_books: tuple[BookSnapshot, ...],
        dropped_count_before: int,
        dropped_count_after: int,
        elapsed_seconds: float,
    ) -> None:
        super().__init__(crossed_error.issue, str(crossed_error))
        self.failure_kind = failure_kind
        self.first_fragment = first_fragment
        self.matching_fragments = matching_fragments
        self.mismatching_fragment = mismatching_fragment
        self.expected_fingerprint = expected_fingerprint
        self.actual_fingerprint = actual_fingerprint
        self.projected_books = projected_books
        self.dropped_count_before = dropped_count_before
        self.dropped_count_after = dropped_count_after
        self.elapsed_seconds = elapsed_seconds

    @property
    def fragments(self) -> tuple[CapturedMarketEvent, ...]:
        fragments = (self.first_fragment, *self.matching_fragments)
        if self.mismatching_fragment is not None:
            return (*fragments, self.mismatching_fragment)
        return fragments


@dataclass(slots=True)
class SplitRevisionContext:
    crossed_error: MarketDataError
    first_fragment: CapturedMarketEvent
    expected_fingerprint: RevisionFingerprint | None
    projected_books: tuple[BookSnapshot, ...]
    dropped_count_before: int
    started_at: float
    matching_fragments: list[CapturedMarketEvent] = field(default_factory=list)

    def failure(
        self,
        failure_kind: CaptureFailureKind,
        *,
        dropped_count_after: int,
        mismatching_fragment: CapturedMarketEvent | None = None,
        actual_fingerprint: RevisionFingerprint | None = None,
    ) -> CaptureContinuityError:
        elapsed_seconds = max(
            0.0,
            asyncio.get_running_loop().time() - self.started_at,
        )
        return CaptureContinuityError(
            self.crossed_error,
            failure_kind=failure_kind,
            first_fragment=self.first_fragment,
            matching_fragments=tuple(self.matching_fragments),
            mismatching_fragment=mismatching_fragment,
            expected_fingerprint=self.expected_fingerprint,
            actual_fingerprint=actual_fingerprint,
            projected_books=self.projected_books,
            dropped_count_before=self.dropped_count_before,
            dropped_count_after=dropped_count_after,
            elapsed_seconds=elapsed_seconds,
        )


def delta_revision_fingerprint(
    event: CapturedMarketEvent,
) -> RevisionFingerprint | None:
    payload = event.payload
    condition_id = event.identity.condition_id
    source_timestamp_ms = event.source_timestamp_ms
    if (
        not isinstance(payload, BookDeltaPayload)
        or condition_id is None
        or source_timestamp_ms is None
    ):
        return None
    source_hashes: dict[str, str] = {}
    for change in payload.changes:
        source_hash = change.source_hash
        if source_hash is None:
            return None
        existing = source_hashes.setdefault(change.token_id, source_hash)
        if existing != source_hash:
            return None
    return RevisionFingerprint(
        condition_id=condition_id,
        source_timestamp_ms=source_timestamp_ms,
        source_hashes=tuple(source_hashes.items()),
    )


def is_revision_continuation(
    required: RevisionFingerprint,
    known_source_hashes: dict[str, str],
    actual: RevisionFingerprint | None,
) -> bool:
    if (
        actual is None
        or actual.condition_id != required.condition_id
        or actual.source_timestamp_ms != required.source_timestamp_ms
    ):
        return False
    actual_hashes = dict(actual.source_hashes)
    required_hashes_match = all(
        actual_hashes.get(token_id) == source_hash
        for token_id, source_hash in required.source_hashes
    )
    known_hashes_match = all(
        known_source_hashes.get(token_id, source_hash) == source_hash
        for token_id, source_hash in actual.source_hashes
    )
    return required_hashes_match and known_hashes_match
