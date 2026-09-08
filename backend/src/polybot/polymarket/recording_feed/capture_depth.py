from __future__ import annotations

from polybot.framework.events.books import BookSnapshot
from polybot.framework.timestamps import require_nonnegative_timestamp
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.markets import Market
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)


class CaptureDepth:
    def __init__(self, market: Market) -> None:
        self._projector = BookDepthProjector((market,))
        self._condition_id = market.condition_id

    @property
    def has_complete_book_baselines(self) -> bool:
        return self._projector.has_complete_baseline(self._condition_id)

    @property
    def baseline_token_ids(self) -> frozenset[str]:
        return self._projector.baseline_token_ids

    def projected_books(self, observed_at_ms: int) -> tuple[BookSnapshot, ...]:
        require_nonnegative_timestamp(observed_at_ms, "observation timestamp")
        return self._projector.snapshots(received_at_ms=observed_at_ms)

    def apply(self, event: CapturedMarketEvent) -> None:
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
