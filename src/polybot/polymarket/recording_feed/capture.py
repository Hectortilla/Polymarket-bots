"""Per-condition package-owned captures over the official market stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Self

from polymarket import PolymarketError

from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.markets import Market
from polybot.polymarket.normalization.recording_events import (
    normalize_recording_event,
)
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.stream_diagnostics import (
    require_monotonic_dropped_count,
    sdk_dropped_count,
)
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)
from polybot.recording.contracts.anomalies import (
    CaptureFailureKind,
    RevisionFingerprint,
)

from .continuity import (
    CaptureContinuityError,
    SplitRevisionContext,
    delta_revision_fingerprint,
)


SPLIT_REVISION_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class MarketCaptureDiagnostics:
    generation: int
    condition_id: str
    dropped_count: int
    has_complete_book_baselines: bool
    baseline_token_ids: frozenset[str]


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
        return sdk_dropped_count(self._handle)

    @property
    def has_complete_book_baselines(self) -> bool:
        return self._projector.has_complete_baseline(self.condition_id)

    def diagnostics(self) -> MarketCaptureDiagnostics:
        return MarketCaptureDiagnostics(
            generation=self.generation,
            condition_id=self.condition_id,
            dropped_count=self.dropped_count,
            has_complete_book_baselines=self.has_complete_book_baselines,
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
        try:
            await self._handle.close()  # type: ignore[attr-defined]
        except PolymarketError as error:
            raise MarketDataTransportError(
                "recording market capture shutdown failed"
            ) from error

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
        try:
            event = await anext(self._events)
        except PolymarketError as error:
            raise MarketDataTransportError("recording market capture failed") from error
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
        started_at_monotonic_seconds = loop.time()
        context = SplitRevisionContext(
            crossed_error=crossed_error,
            first_fragment=first,
            expected_fingerprint=delta_revision_fingerprint(first),
            projected_books=self.projected_books(first.source_timestamp_ms or 0),
            dropped_count_before=dropped_count_before,
            started_at_monotonic_seconds=started_at_monotonic_seconds,
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
            actual_fingerprint = delta_revision_fingerprint(continuation)
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
        context: SplitRevisionContext,
        failure_kind: CaptureFailureKind,
    ) -> None:
        self._raise_if_dropped(context)
        raise context.failure(
            failure_kind,
            dropped_count_after=self.dropped_count,
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
            self.dropped_count,
        )
        if dropped_count_after == context.dropped_count_before:
            return
        raise context.failure(
            CaptureFailureKind.SDK_HANDLE_DROP,
            dropped_count_after=dropped_count_after,
            mismatching_fragment=mismatching_fragment,
            actual_fingerprint=actual_fingerprint,
        )
