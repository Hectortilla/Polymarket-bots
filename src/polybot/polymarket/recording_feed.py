"""Per-condition official-SDK feed for historical market recording."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
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
from polybot.polymarket.types import Market
from polybot.recording.contracts import BookBaselinePayload, BookDeltaPayload


SPLIT_REVISION_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class MarketCaptureDiagnostics:
    generation: int
    condition_id: str
    dropped_count: int
    ready: bool
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
        self._pending: CapturedMarketEvent | None = None

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
            captured = await self._next_captured()
            if captured is None:
                continue
            try:
                self._apply_depth(captured)
            except MarketDataError as error:
                if error.issue is not MarketDataIssue.CROSSED_BOOK:
                    raise
                return await self._complete_split_revision(captured, error)
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
        if self._pending is not None:
            pending = self._pending
            self._pending = None
            return pending
        event = await anext(self._events)
        return normalize_recording_event(event, market=self._market)

    async def _complete_split_revision(
        self,
        first: CapturedMarketEvent,
        crossed_error: MarketDataError,
    ) -> CapturedMarketEvent:
        """Join source fragments that are invalid only before their revision ends."""
        revision_key = _delta_revision_key(first)
        if revision_key is None:
            raise crossed_error
        combined = first
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._split_revision_timeout_seconds
        while True:
            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                raise crossed_error
            try:
                continuation = await asyncio.wait_for(
                    self._next_captured(),
                    timeout=remaining_seconds,
                )
            except (TimeoutError, StopAsyncIteration):
                raise crossed_error from None
            if continuation is None:
                continue
            if _delta_revision_key(continuation) != revision_key:
                self._pending = continuation
                raise crossed_error
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
            try:
                self._apply_depth(combined)
            except MarketDataError as error:
                if error.issue is MarketDataIssue.CROSSED_BOOK:
                    continue
                raise
            return combined


type _DeltaRevisionKey = tuple[str, int, tuple[tuple[str, str], ...]]


def _delta_revision_key(event: CapturedMarketEvent) -> _DeltaRevisionKey | None:
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
    return (
        condition_id,
        source_timestamp_ms,
        tuple(sorted(source_hashes.items())),
    )


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
