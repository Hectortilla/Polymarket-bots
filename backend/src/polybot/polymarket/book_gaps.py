from __future__ import annotations

from collections.abc import Callable

from polybot.framework.events.books import BookGapEvent, BookGapReason
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
)
from polybot.polymarket.markets import (
    Market,
)

from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketEvent,
    MarketPriceChangeEvent,
)

_BOOK_GAP_REASONS: dict[MarketDataIssue, BookGapReason] = {
    MarketDataIssue.INVALID_MARKET_PARAMETERS: (
        BookGapReason.INVALID_MARKET_PARAMETERS
    ),
    MarketDataIssue.INVALID_BOOK_LEVEL: BookGapReason.INVALID_BOOK_LEVEL,
    MarketDataIssue.INVALID_BOOK_SIDE: BookGapReason.INVALID_BOOK_SIDE,
    MarketDataIssue.MISSING_BOOK_BASELINE: BookGapReason.MISSING_BOOK_BASELINE,
    MarketDataIssue.BOOK_IDENTITY_MISMATCH: (BookGapReason.BOOK_IDENTITY_MISMATCH),
    MarketDataIssue.BOOK_STREAM_GAP: BookGapReason.BOOK_STREAM_GAP,
    MarketDataIssue.CROSSED_BOOK: BookGapReason.CROSSED_BOOK,
}


class MarketBookGaps:
    def __init__(self, now_ms: Callable[[], int]) -> None:
        self._now_ms = now_ms
        self._last_book_gap: BookGapEvent | None = None
        self._book_gap_count = 0

    @property
    def last(self) -> BookGapEvent | None:
        return self._last_book_gap

    @property
    def count(self) -> int:
        return self._book_gap_count

    def invalidate_rejected(
        self,
        projector: BookDepthProjector,
        event: MarketEvent,
        market: Market,
        *,
        issue: MarketDataIssue,
        observed_at_ms: int | None = None,
    ) -> BookGapEvent | None:
        if not isinstance(event, (MarketBookEvent, MarketPriceChangeEvent)):
            return None
        projector.invalidate_condition(market.condition_id)
        return self.record(
            issue,
            condition_id=market.condition_id,
            observed_at_ms=self._now_ms() if observed_at_ms is None else observed_at_ms,
        )

    def invalidate_unrouteable(
        self,
        projector: BookDepthProjector,
        event: MarketEvent,
        *,
        issue: MarketDataIssue = MarketDataIssue.INVALID_MARKET_PARAMETERS,
    ) -> BookGapEvent | None:
        if not isinstance(event, (MarketBookEvent, MarketPriceChangeEvent)):
            return None
        projector.clear()
        return self.record(
            issue,
            condition_id=None,
            observed_at_ms=self._now_ms(),
        )

    def record(
        self,
        issue: MarketDataIssue,
        *,
        condition_id: str | None,
        observed_at_ms: int,
    ) -> BookGapEvent:
        self._book_gap_count += 1
        try:
            reason = _BOOK_GAP_REASONS[issue]
        except KeyError as error:
            raise MarketDataError(
                MarketDataIssue.INVALID_STREAM_DIAGNOSTICS,
                f"unsupported book-gap issue: {issue.value}",
            ) from error
        gap = BookGapEvent(
            condition_id=condition_id,
            observed_at_ms=observed_at_ms,
            reason=reason,
        )
        self._last_book_gap = gap
        return gap
