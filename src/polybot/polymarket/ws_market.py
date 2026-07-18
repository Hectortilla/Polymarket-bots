from __future__ import annotations

import time
from collections.abc import AsyncIterator
from collections.abc import Callable, Iterable

from polymarket import AsyncPublicClient
from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketEvent,
    MarketLastTradePriceEvent,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
    MarketTickSizeChangeEvent,
)
from polymarket.streams import MarketSpec

from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.normalization.recording_events import (
    MARKET_WEBSOCKET_SOURCE,
    normalize_recording_event,
)
from polybot.polymarket.types import (
    Market,
    MarketTradeHint,
    index_markets_by_token,
)
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookDeltaPayload,
    PublicTradePayload,
    ResolutionPayload,
)


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
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._market_by_token: dict[str, Market] = {}
        self._market_by_condition: dict[str, Market] = {}
        self.set_markets(markets)

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
        stream = await self._client.subscribe(
            MarketSpec(
                token_ids=tuple(sorted(normalized_token_ids)),
                custom_feature_enabled=True,
            ),
        )
        async with stream:
            async for event in stream:
                market = _market_for_event(
                    event,
                    subscribed_token_ids=normalized_token_ids,
                    market_by_token=market_by_token,
                    market_by_condition=market_by_condition,
                )
                if market is None:
                    continue
                try:
                    captured = normalize_recording_event(event, market=market)
                except (MarketDataError, ValueError):
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
                    except MarketDataError:
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
                    except MarketDataError:
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
            await self._client.close()


def _identifier(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _market_for_event(
    event: MarketEvent,
    *,
    subscribed_token_ids: frozenset[str],
    market_by_token: dict[str, Market],
    market_by_condition: dict[str, Market],
) -> Market | None:
    if isinstance(event, (MarketPriceChangeEvent, MarketResolvedEvent)):
        condition_id = _identifier(event.payload.market)
        return None if condition_id is None else market_by_condition.get(condition_id)
    if isinstance(
        event,
        (MarketBookEvent, MarketLastTradePriceEvent, MarketTickSizeChangeEvent),
    ):
        token_id = _identifier(event.payload.token_id)
        if token_id is None or token_id not in subscribed_token_ids:
            return None
        return market_by_token.get(token_id)
    return None
