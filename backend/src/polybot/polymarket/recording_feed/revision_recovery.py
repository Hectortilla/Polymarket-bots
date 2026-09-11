from __future__ import annotations

import asyncio

from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
)
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.recording_feed.continuity import (
    SplitRevisionContext,
)
from polybot.polymarket.stream_diagnostics import (
    require_monotonic_dropped_count,
)
from polybot.recording.contracts.anomalies import (
    CaptureFailureKind,
    RevisionFingerprint,
)
from polybot.recording.contracts.book import (
    BookDeltaPayload,
)

from .capture_depth import CaptureDepth
from .capture_source import CaptureSource


class SplitRevisionRecovery:
    def __init__(
        self, source: CaptureSource, depth: CaptureDepth, timeout_seconds: float
    ) -> None:
        self._source = source
        self._depth = depth
        self._split_revision_timeout_seconds = timeout_seconds

    async def complete(
        self,
        first: CapturedMarketEvent,
        crossed_error: MarketDataError,
        *,
        dropped_count_before: int,
    ) -> CapturedMarketEvent:
        """Join source fragments that are invalid only before their revision ends."""
        loop = asyncio.get_running_loop()
        started_at_monotonic_seconds = loop.time()
        context = SplitRevisionContext(
            crossed_error=crossed_error,
            first_fragment=first,
            expected_fingerprint=first.delta_revision_fingerprint(),
            projected_books=self._depth.projected_books(first.source_timestamp_ms or 0),
            dropped_count_before=dropped_count_before,
            started_at_monotonic_seconds=started_at_monotonic_seconds,
        )
        self._raise_if_dropped(context)
        required_fingerprint = context.expected_fingerprint
        if required_fingerprint is None:
            raise context.failure(
                CaptureFailureKind.SPLIT_REVISION_MISMATCH,
                dropped_count_after=self._source.dropped_count,
            )
        known_source_hashes = dict(required_fingerprint.source_hashes)
        combined = first
        deadline_seconds = loop.time() + self._split_revision_timeout_seconds
        while True:
            remaining_seconds = deadline_seconds - loop.time()
            if remaining_seconds <= 0:
                self._raise_wait_failure(
                    context,
                    CaptureFailureKind.SPLIT_REVISION_TIMEOUT,
                )
            try:
                continuation = await asyncio.wait_for(
                    self._source.next_captured(),
                    timeout=remaining_seconds,
                )
            except TimeoutError:
                self._raise_wait_failure(
                    context,
                    CaptureFailureKind.SPLIT_REVISION_TIMEOUT,
                )
            except StopAsyncIteration:
                self._raise_wait_failure(
                    context,
                    CaptureFailureKind.SPLIT_REVISION_END,
                )
            except MarketDataError:
                self._raise_if_dropped(context)
                raise context.failure(
                    CaptureFailureKind.SPLIT_REVISION_MISMATCH,
                    dropped_count_after=self._source.dropped_count,
                ) from None
            if continuation is None:
                self._raise_if_dropped(context)
                raise context.failure(
                    CaptureFailureKind.SPLIT_REVISION_MISMATCH,
                    dropped_count_after=self._source.dropped_count,
                )
            actual_fingerprint = continuation.delta_revision_fingerprint()
            is_match = required_fingerprint.accepts_continuation(
                actual_fingerprint,
                known_source_hashes=known_source_hashes,
            )
            mismatching_fragment = None if is_match else continuation
            if is_match:
                context.matching_fragments.append(continuation)
            self._raise_if_dropped(
                context,
                mismatching_fragment=mismatching_fragment,
                actual_fingerprint=actual_fingerprint,
            )
            if not is_match:
                raise context.failure(
                    CaptureFailureKind.SPLIT_REVISION_MISMATCH,
                    dropped_count_after=self._source.dropped_count,
                    mismatching_fragment=continuation,
                    actual_fingerprint=actual_fingerprint,
                )
            if actual_fingerprint is None:
                raise AssertionError("matching split revision has no fingerprint")
            known_source_hashes.update(actual_fingerprint.source_hashes)
            context.expected_fingerprint = RevisionFingerprint(
                condition_id=required_fingerprint.condition_id,
                source_timestamp_ms=required_fingerprint.source_timestamp_ms,
                source_hashes=tuple(known_source_hashes.items()),
            )
            first_payload = combined.payload
            continuation_payload = continuation.payload
            if not isinstance(first_payload, BookDeltaPayload) or not isinstance(
                continuation_payload,
                BookDeltaPayload,
            ):
                raise AssertionError("split revision key requires book deltas")
            combined = CapturedMarketEvent(
                source_timestamp_ms=combined.source_timestamp_ms,
                identity=combined.identity,
                payload=BookDeltaPayload(
                    changes=first_payload.changes + continuation_payload.changes,
                ),
            )
            self._raise_if_dropped(
                context,
                actual_fingerprint=actual_fingerprint,
            )
            try:
                self._depth.apply(combined)
            except MarketDataError as error:
                if error.issue is MarketDataIssue.CROSSED_BOOK:
                    continue
                raise
            return combined

    def _raise_wait_failure(
        self,
        context: SplitRevisionContext,
        failure_kind: CaptureFailureKind,
    ) -> None:
        self._raise_if_dropped(context)
        raise context.failure(
            failure_kind,
            dropped_count_after=self._source.dropped_count,
        )

    def _raise_if_dropped(
        self,
        context: SplitRevisionContext,
        *,
        mismatching_fragment: CapturedMarketEvent | None = None,
        actual_fingerprint: RevisionFingerprint | None = None,
    ) -> None:
        dropped_count_after = require_monotonic_dropped_count(
            context.dropped_count_before,
            self._source.dropped_count,
        )
        if dropped_count_after == context.dropped_count_before:
            return
        raise context.failure(
            CaptureFailureKind.SDK_HANDLE_DROP,
            dropped_count_after=dropped_count_after,
            mismatching_fragment=mismatching_fragment,
            actual_fingerprint=actual_fingerprint,
        )
