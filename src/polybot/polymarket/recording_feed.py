"""Per-condition official-SDK feed for historical market recording."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Self

from polymarket import AsyncPublicClient
from polymarket.streams import MarketSpec

from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.normalization.recording_events import (
    normalize_recording_event,
)
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.markets import Market
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookDeltaPayload,
    CaptureFailureKind,
    RevisionFingerprint,
)


SPLIT_REVISION_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class MarketCaptureDiagnostics:
    generation: int
    condition_id: str
    dropped_count: int
    ready: bool
    baseline_token_ids: frozenset[str]


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
class _SplitRevisionContext:
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


class MarketCapture(AsyncIterator[CapturedMarketEvent]):
    def __init__(
        self,
        handle: object,
        *,
        market: Market,
        generation: int,
        split_revision_timeout_seconds: float = SPLIT_REVISION_TIMEOUT_SECONDS,
    ) -> None:
        if split_revision_timeout_seconds <= 0:
            raise ValueError("split revision timeout must be positive")
        self._handle = handle
        self._events = handle.__aiter__()  # type: ignore[attr-defined]
        self._market = market
        self._generation = generation
        self._projector = BookDepthProjector((market,))
        self._split_revision_timeout_seconds = split_revision_timeout_seconds

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def condition_id(self) -> str:
        return self._market.condition_id

    @property
    def dropped_count(self) -> int:
        value = getattr(self._handle, "dropped", 0)
        return value if isinstance(value, int) and value >= 0 else 0

    @property
    def ready(self) -> bool:
        return set(self._market.token_ids) <= self._projector.baseline_token_ids

    def diagnostics(self) -> MarketCaptureDiagnostics:
        return MarketCaptureDiagnostics(
            generation=self.generation,
            condition_id=self.condition_id,
            dropped_count=self.dropped_count,
            ready=self.ready,
            baseline_token_ids=self._projector.baseline_token_ids,
        )

    def projected_books(self, observed_at_ms: int) -> tuple[BookSnapshot, ...]:
        if observed_at_ms < 0:
            raise ValueError("observation timestamp must not be negative")
        return self._projector.snapshots(received_at_ms=observed_at_ms)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> CapturedMarketEvent:
        while True:
            dropped_count_before = self.dropped_count
            captured = await self._next_captured()
            if captured is None:
                continue
            try:
                self._apply_depth(captured)
            except MarketDataError as error:
                if error.issue is not MarketDataIssue.CROSSED_BOOK:
                    raise
                return await self._complete_split_revision(
                    captured,
                    error,
                    dropped_count_before=dropped_count_before,
                )
            else:
                return captured

    async def close(self) -> None:
        await self._handle.close()  # type: ignore[attr-defined]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    def _apply_depth(self, event: CapturedMarketEvent) -> None:
        condition_id = event.identity.condition_id
        if condition_id is None:
            raise AssertionError("captured market event has no condition identity")
        received_at_ms = event.source_timestamp_ms or 0
        if isinstance(event.payload, BookBaselinePayload):
            self._projector.apply_baseline(
                event.payload,
                condition_id=condition_id,
                received_at_ms=received_at_ms,
            )
        elif isinstance(event.payload, BookDeltaPayload):
            self._projector.apply_delta(
                event.payload,
                condition_id=condition_id,
                received_at_ms=received_at_ms,
            )

    async def _next_captured(self) -> CapturedMarketEvent | None:
        event = await anext(self._events)
        return normalize_recording_event(event, market=self._market)

    async def _complete_split_revision(
        self,
        first: CapturedMarketEvent,
        crossed_error: MarketDataError,
        *,
        dropped_count_before: int,
    ) -> CapturedMarketEvent:
        """Join source fragments that are invalid only before their revision ends."""
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        context = _SplitRevisionContext(
            crossed_error=crossed_error,
            first_fragment=first,
            expected_fingerprint=_delta_revision_fingerprint(first),
            projected_books=self.projected_books(first.source_timestamp_ms or 0),
            dropped_count_before=dropped_count_before,
            started_at=started_at,
        )
        self._raise_if_dropped(context)
        required_fingerprint = context.expected_fingerprint
        if required_fingerprint is None:
            raise context.failure(
                CaptureFailureKind.SPLIT_REVISION_MISMATCH,
                dropped_count_after=self.dropped_count,
            )
        known_source_hashes = dict(required_fingerprint.source_hashes)
        combined = first
        deadline = loop.time() + self._split_revision_timeout_seconds
        while True:
            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                self._raise_wait_failure(
                    context,
                    CaptureFailureKind.SPLIT_REVISION_TIMEOUT,
                )
            try:
                continuation = await asyncio.wait_for(
                    self._next_captured(),
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
                    dropped_count_after=self.dropped_count,
                ) from None
            if continuation is None:
                self._raise_if_dropped(context)
                raise context.failure(
                    CaptureFailureKind.SPLIT_REVISION_MISMATCH,
                    dropped_count_after=self.dropped_count,
                )
            actual_fingerprint = _delta_revision_fingerprint(continuation)
            is_match = _is_revision_continuation(
                required_fingerprint,
                known_source_hashes,
                actual_fingerprint,
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
                    dropped_count_after=self.dropped_count,
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
                self._apply_depth(combined)
            except MarketDataError as error:
                if error.issue is MarketDataIssue.CROSSED_BOOK:
                    continue
                raise
            return combined

    def _raise_wait_failure(
        self,
        context: _SplitRevisionContext,
        failure_kind: CaptureFailureKind,
    ) -> None:
        self._raise_if_dropped(context)
        raise context.failure(
            failure_kind,
            dropped_count_after=self.dropped_count,
        )

    def _raise_if_dropped(
        self,
        context: _SplitRevisionContext,
        *,
        mismatching_fragment: CapturedMarketEvent | None = None,
        actual_fingerprint: RevisionFingerprint | None = None,
    ) -> None:
        dropped_count_after = self.dropped_count
        if dropped_count_after <= context.dropped_count_before:
            return
        raise context.failure(
            CaptureFailureKind.SDK_HANDLE_DROP,
            dropped_count_after=dropped_count_after,
            mismatching_fragment=mismatching_fragment,
            actual_fingerprint=actual_fingerprint,
        )


def _delta_revision_fingerprint(
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


def _is_revision_continuation(
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


class MarketRecordingFeed:
    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._client = client or AsyncPublicClient()
        self._owns_client = client is None

    async def open_capture(
        self,
        market: Market,
        *,
        generation: int,
    ) -> MarketCapture:
        if generation < 0:
            raise ValueError("subscription generation must not be negative")
        handle = await self._client.subscribe(
            MarketSpec(
                token_ids=market.token_ids,
                custom_feature_enabled=True,
            )
        )
        return MarketCapture(handle, market=market, generation=generation)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()
