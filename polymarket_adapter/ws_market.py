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

from bots.framework.events import Side
from bots.framework.events.books import BookSnapshot
from bots.polymarket.errors import MarketDataError, MarketDataIssue
from bots.polymarket.normalization.book import (
    normalize_book,
    normalize_price_change_level,
)
from bots.polymarket.types import Market, index_markets_by_token


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
        self.set_markets(markets)

    def set_markets(self, markets: Iterable[Market]) -> None:
        self._market_by_token = index_markets_by_token(markets)

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
                pending_levels: dict[
                    str,
                    tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]],
                ] = {}
                invalid_tokens: set[str] = set()
                for change in event.payload.price_changes:
                    token_id = str(change.token_id)
                    sides = depth.get(token_id)
                    if token_id not in normalized_token_ids or sides is None:
                        continue
                    if token_id in invalid_tokens:
                        continue
                    try:
                        side = _normalize_price_change_side(change.side)
                        level = normalize_price_change_level(
                            price=change.price,
                            size=change.size,
                        )
                    except MarketDataError:
                        invalid_tokens.add(token_id)
                        pending_levels.pop(token_id, None)
                        continue
                    bid_ask_levels = pending_levels.setdefault(
                        token_id,
                        (sides[0].copy(), sides[1].copy()),
                    )
                    levels = bid_ask_levels[0] if side is Side.BUY else bid_ask_levels[1]
                    if level.size == 0:
                        levels.pop(level.price, None)
                    else:
                        levels[level.price] = level.size
                for token_id, bid_ask_levels in pending_levels.items():
                    snapshot = self._snapshot(
                        token_id,
                        event.payload.market,
                        *bid_ask_levels,
                    )
                    if snapshot is not None:
                        depth[token_id] = bid_ask_levels
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
                expected_token_id=token_id,
                expected_condition_id=market.condition_id if market else None,
            )
        except MarketDataError:
            return None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()


def _normalize_price_change_side(value: object) -> Side:
    try:
        return Side(value)
    except (TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_SIDE,
            "price change side is invalid",
        ) from error
