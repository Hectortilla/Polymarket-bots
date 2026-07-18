"""Per-condition official-SDK feed for historical market recording."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Self

from polymarket import AsyncPublicClient
from polymarket.streams import MarketSpec

from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.normalization.recording_events import (
    normalize_recording_event,
)
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.types import Market
from polybot.recording.contracts import BookBaselinePayload, BookDeltaPayload


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
    ) -> None:
        self._handle = handle
        self._events = handle.__aiter__()  # type: ignore[attr-defined]
        self._market = market
        self._generation = generation
        self._projector = BookDepthProjector((market,))

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
            event = await anext(self._events)
            captured = normalize_recording_event(event, market=self._market)
            if captured is None:
                continue
            self._apply_depth(captured)
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
