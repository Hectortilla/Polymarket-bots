"""Continuity evidence for split market-book revisions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.errors import MarketDataError
from polybot.polymarket.recording_events import CapturedMarketEvent
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
    started_at_monotonic_seconds: float
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
            asyncio.get_running_loop().time() - self.started_at_monotonic_seconds,
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
