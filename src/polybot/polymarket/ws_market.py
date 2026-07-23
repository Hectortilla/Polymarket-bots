from __future__ import annotations

from collections.abc import AsyncIterator
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from polymarket import AsyncPublicClient, PolymarketError
from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketEvent,
    MarketLastTradePriceEvent,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
    MarketTickSizeChangeEvent,
)
from polymarket.streams import MarketSpec

from polybot.framework.clock import system_now_ms
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.client_lifecycle import close_owned_public_client
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.normalization.recording_events import (
    MARKET_WEBSOCKET_SOURCE,
    normalize_recording_event,
)
from polybot.polymarket.markets import (
    Market,
    index_markets_by_token,
)
from polybot.polymarket.market_hints import MarketTradeHint
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)


@dataclass(frozen=True, slots=True)
class MarketStreamBookGap:
    """A stream continuity loss that requires a replacement book baseline."""

    issue: MarketDataIssue
    condition_id: str | None
    observed_at_ms: int


class MarketStream:
    def __init__(
        self,
        client: AsyncPublicClient | None = None,
        *,
        markets: Iterable[Market] = (),
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client or AsyncPublicClient()
        self._owns_client = client is None
        self._now_ms = now_ms or system_now_ms
        self._market_by_token: dict[str, Market] = {}
        self._market_by_condition: dict[str, Market] = {}
        self._last_book_gap: MarketStreamBookGap | None = None
        self._book_gap_count = 0
        self.set_markets(markets)

    @property
    def last_book_gap(self) -> MarketStreamBookGap | None:
        """Return the most recent typed reason a book baseline was invalidated."""
        return self._last_book_gap

    @property
    def book_gap_count(self) -> int:
        """Return the number of book continuity losses for this adapter."""
        return self._book_gap_count

    def set_markets(self, markets: Iterable[Market]) -> None:
        normalized = tuple(markets)
        self._market_by_token = index_markets_by_token(normalized)
        self._market_by_condition = {
            market.condition_id: market for market in normalized
        }

    async def books(self, token_ids: set[str]) -> AsyncIterator[BookSnapshot]:
        async for event in self.events(token_ids):
            if isinstance(event, BookSnapshot):
                yield event

    async def events(
        self,
        token_ids: set[str],
    ) -> AsyncIterator[BookSnapshot | MarketTradeHint | MarketResolutionEvent]:
        normalized_token_ids = frozenset(token_id for token_id in token_ids if token_id)
        if len(normalized_token_ids) != len(token_ids) or not normalized_token_ids:
            raise MarketDataError(
                MarketDataIssue.EMPTY_IDENTIFIER,
                "at least one non-empty token ID is required",
            )

        # A subscription is one immutable market generation.  The runner may
        # replace the next generation while an SDK event from this one is
        # still being delivered; keep identity normalization tied to this
        # generation instead of observing the mutable adapter-wide registry.
        market_by_token = self._market_by_token.copy()
        market_by_condition = self._market_by_condition.copy()
        projector = BookDepthProjector(market_by_condition.values())
        try:
            stream = await self._client.subscribe(
                MarketSpec(
                    token_ids=tuple(sorted(normalized_token_ids)),
                    custom_feature_enabled=True,
                ),
            )
        except PolymarketError as error:
            raise MarketDataTransportError(
                "market stream subscription failed"
            ) from error
        dropped_count = _dropped_count(stream)
        async with _normalized_subscription(stream) as subscribed_events:
            async for event in subscribed_events:
                current_dropped_count = _dropped_count(stream)
                if current_dropped_count > dropped_count:
                    projector.clear()
                    self._record_book_gap(
                        MarketDataIssue.BOOK_STREAM_GAP,
                        condition_id=None,
                        observed_at_ms=self._now_ms(),
                    )
                dropped_count = max(dropped_count, current_dropped_count)
                try:
                    market = _market_for_event(
                        event,
                        subscribed_token_ids=normalized_token_ids,
                        market_by_token=market_by_token,
                        market_by_condition=market_by_condition,
                    )
                    if market is None:
                        self._invalidate_unrouteable_book_frame(projector, event)
                        continue
                except (AttributeError, MarketDataError, ValueError) as error:
                    self._invalidate_unrouteable_book_frame(
                        projector,
                        event,
                        issue=_market_data_issue(error),
                    )
                    continue
                try:
                    captured = normalize_recording_event(event, market=market)
                except (AttributeError, MarketDataError, ValueError) as error:
                    self._invalidate_rejected_book_frame(
                        projector,
                        event,
                        market,
                        issue=_market_data_issue(error),
                    )
                    continue
                if captured is None:
                    continue

                condition_id = captured.identity.condition_id
                if condition_id is None:
                    continue
                observed_at_ms = self._now_ms()
                if isinstance(captured.payload, BookBaselinePayload):
                    try:
                        yield projector.apply_baseline(
                            captured.payload,
                            condition_id=condition_id,
                            received_at_ms=observed_at_ms,
                        )
                    except MarketDataError as error:
                        self._invalidate_rejected_book_frame(
                            projector,
                            event,
                            market,
                            issue=error.issue,
                            observed_at_ms=observed_at_ms,
                        )
                        continue
                elif isinstance(captured.payload, BookDeltaPayload):
                    changes = tuple(
                        change
                        for change in captured.payload.changes
                        if change.token_id in normalized_token_ids
                        and change.token_id in projector.baseline_token_ids
                    )
                    if not changes:
                        continue
                    try:
                        snapshots = projector.apply_delta(
                            BookDeltaPayload(changes=changes),
                            condition_id=condition_id,
                            received_at_ms=observed_at_ms,
                        )
                    except MarketDataError as error:
                        self._invalidate_rejected_book_frame(
                            projector,
                            event,
                            market,
                            issue=error.issue,
                            observed_at_ms=observed_at_ms,
                        )
                        continue
                    for snapshot in snapshots:
                        yield snapshot
                elif isinstance(captured.payload, PublicTradePayload):
                    yield MarketTradeHint(
                        condition_id,
                        captured.payload.token_id,
                        market.slug,
                        observed_at_ms,
                    )
                elif isinstance(captured.payload, ResolutionPayload):
                    yield MarketResolutionEvent(
                        condition_id=condition_id,
                        market_slug=market.slug,
                        token_ids=market.token_ids,
                        winning_token_id=captured.payload.winning_token_id,
                        winning_outcome=captured.payload.winning_outcome,
                        resolved_at_ms=(
                            captured.source_timestamp_ms
                            if captured.source_timestamp_ms is not None
                            else observed_at_ms
                        ),
                        source=captured.payload.source,
                    )

    async def close(self) -> None:
        if self._owns_client:
            await close_owned_public_client(self._client)

    def _invalidate_rejected_book_frame(
        self,
        projector: BookDepthProjector,
        event: MarketEvent,
        market: Market,
        *,
        issue: MarketDataIssue,
        observed_at_ms: int | None = None,
    ) -> None:
        if not isinstance(event, (MarketBookEvent, MarketPriceChangeEvent)):
            return
        projector.invalidate_condition(market.condition_id)
        self._record_book_gap(
            issue,
            condition_id=market.condition_id,
            observed_at_ms=self._now_ms()
            if observed_at_ms is None
            else observed_at_ms,
        )

    def _invalidate_unrouteable_book_frame(
        self,
        projector: BookDepthProjector,
        event: MarketEvent,
        *,
        issue: MarketDataIssue = MarketDataIssue.INVALID_MARKET_PARAMETERS,
    ) -> None:
        if not isinstance(event, (MarketBookEvent, MarketPriceChangeEvent)):
            return
        projector.clear()
        self._record_book_gap(
            issue,
            condition_id=None,
            observed_at_ms=self._now_ms(),
        )

    def _record_book_gap(
        self,
        issue: MarketDataIssue,
        *,
        condition_id: str | None,
        observed_at_ms: int,
    ) -> None:
        self._book_gap_count += 1
        self._last_book_gap = MarketStreamBookGap(
            issue=issue,
            condition_id=condition_id,
            observed_at_ms=observed_at_ms,
        )


def _identifier(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


@asynccontextmanager
async def _normalized_subscription(stream: object) -> AsyncIterator[object]:
    """Normalize SDK stream lifecycle failures at the adapter boundary."""
    try:
        async with stream:  # type: ignore[attr-defined]
            yield stream
    except PolymarketError as error:
        raise MarketDataTransportError("market stream failed") from error


def _dropped_count(stream: object) -> int:
    value = getattr(stream, "dropped", 0)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _market_data_issue(error: BaseException) -> MarketDataIssue:
    if isinstance(error, MarketDataError):
        return error.issue
    return MarketDataIssue.INVALID_MARKET_PARAMETERS


def _market_for_event(
    event: MarketEvent,
    *,
    subscribed_token_ids: frozenset[str],
    market_by_token: dict[str, Market],
    market_by_condition: dict[str, Market],
) -> Market | None:
    payload = getattr(event, "payload", None)
    if isinstance(event, (MarketPriceChangeEvent, MarketResolvedEvent)):
        condition_id = _identifier(getattr(payload, "market", None))
        return None if condition_id is None else market_by_condition.get(condition_id)
    if isinstance(
        event,
        (MarketBookEvent, MarketLastTradePriceEvent, MarketTickSizeChangeEvent),
    ):
        token_id = _identifier(getattr(payload, "token_id", None))
        if token_id is None or token_id not in subscribed_token_ids:
            return None
        return market_by_token.get(token_id)
    return None
