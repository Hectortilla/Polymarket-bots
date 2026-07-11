from __future__ import annotations

import time
from collections.abc import AsyncIterator
from collections.abc import Callable, Iterable
from decimal import Decimal

from polymarket import AsyncPublicClient
from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketPriceChangeEvent,
)
from polymarket.models.clob.order_book import OrderBookLevel
from polymarket.streams import MarketSpec

from bots.framework.events.books import BookSnapshot
from bots.polymarket.errors import MarketDataError, MarketDataIssue
from bots.polymarket.normalization import normalize_book
from bots.polymarket.types import Market


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
        self._market_by_token = {
            token_id: market
            for market in markets
            for token_id in (market.yes_token_id, market.no_token_id)
        }

    async def books(self, token_ids: set[str]) -> AsyncIterator[BookSnapshot]:
        normalized_token_ids = frozenset(token_id for token_id in token_ids if token_id)
        if len(normalized_token_ids) != len(token_ids) or not normalized_token_ids:
            raise MarketDataError(
                MarketDataIssue.EMPTY_IDENTIFIER,
                "at least one non-empty token ID is required",
            )

        depth: dict[str, tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]] = {}
        stream = await self._client.subscribe(
            MarketSpec(token_ids=tuple(sorted(normalized_token_ids))),
        )
        async with stream:
            async for event in stream:
                if isinstance(event, MarketBookEvent):
                    payload = event.payload
                    token_id = str(payload.token_id)
                    if token_id not in normalized_token_ids:
                        continue
                    depth[token_id] = (
                        {level.price: level.size for level in payload.bids},
                        {level.price: level.size for level in payload.asks},
                    )
                    snapshot = self._snapshot(
                        token_id,
                        payload.market,
                        *depth[token_id],
                    )
                    if snapshot is not None:
                        yield snapshot
                    else:
                        depth.pop(token_id, None)
                    continue

                if not isinstance(event, MarketPriceChangeEvent):
                    continue
                candidates: dict[
                    str,
                    tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]],
                ] = {}
                for change in event.payload.price_changes:
                    token_id = str(change.token_id)
                    sides = depth.get(token_id)
                    if token_id not in normalized_token_ids or sides is None:
                        continue
                    candidate = candidates.setdefault(
                        token_id,
                        (sides[0].copy(), sides[1].copy()),
                    )
                    levels = candidate[0] if change.side == "BUY" else candidate[1]
                    if change.size == 0:
                        levels.pop(change.price, None)
                    else:
                        levels[change.price] = change.size
                for token_id, candidate in candidates.items():
                    snapshot = self._snapshot(
                        token_id,
                        event.payload.market,
                        *candidate,
                    )
                    if snapshot is not None:
                        depth[token_id] = candidate
                        yield snapshot

    def _snapshot(
        self,
        token_id: str,
        condition_id: str,
        bids: dict[Decimal, Decimal],
        asks: dict[Decimal, Decimal],
    ) -> BookSnapshot | None:
        market = self._market_by_token.get(token_id)
        try:
            return normalize_book(
                token_id=token_id,
                bids=tuple(
                    OrderBookLevel(price=price, size=size)
                    for price, size in bids.items()
                ),
                asks=tuple(
                    OrderBookLevel(price=price, size=size)
                    for price, size in asks.items()
                ),
                received_at_ms=self._now_ms(),
                condition_id=condition_id,
                market_slug=market.slug if market else None,
            )
        except MarketDataError:
            return None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()
