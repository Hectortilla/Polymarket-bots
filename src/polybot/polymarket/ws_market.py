from __future__ import annotations

import time
from collections.abc import AsyncIterator
from collections.abc import Callable, Iterable
from decimal import Decimal

from polymarket import AsyncPublicClient
from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketLastTradePriceEvent,
    MarketPriceChangeEvent,
    MarketResolvedEvent,
)
from polymarket.models.clob.order_book import OrderBookLevel
from polymarket.streams import MarketSpec

from polybot.framework.events import Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.resolutions import normalize_outcome
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.normalization.book import (
    normalize_book,
    normalize_price_change_level,
)
from polybot.polymarket.types import (
    Market,
    MarketTradeHint,
    index_markets_by_token,
    outcome_label_for_token,
)

MARKET_WEBSOCKET_SOURCE = "market_websocket"


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

        depth: dict[str, tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]] = {}
        stream = await self._client.subscribe(
            MarketSpec(
                token_ids=tuple(sorted(normalized_token_ids)),
                custom_feature_enabled=True,
            ),
        )
        async with stream:
            async for event in stream:
                if isinstance(event, MarketResolvedEvent):
                    resolution = self._resolution(event)
                    if resolution is not None:
                        yield resolution
                    continue
                if isinstance(event, MarketLastTradePriceEvent):
                    payload = event.payload
                    token_id = _identifier(payload.token_id)
                    condition_id = _identifier(payload.market)
                    if token_id is None or condition_id is None:
                        continue
                    market = self._market_by_token.get(token_id)
                    if token_id in normalized_token_ids:
                        yield MarketTradeHint(
                            condition_id=condition_id,
                            token_id=token_id,
                            market_slug=market.slug if market else None,
                            occurred_at_ms=self._now_ms(),
                        )
                    continue
                if isinstance(event, MarketBookEvent):
                    payload = event.payload
                    token_id = _identifier(payload.token_id)
                    condition_id = _identifier(payload.market)
                    if token_id is None or condition_id is None:
                        continue
                    if token_id not in normalized_token_ids:
                        continue
                    depth[token_id] = (
                        {level.price: level.size for level in payload.bids},
                        {level.price: level.size for level in payload.asks},
                    )
                    snapshot = self._snapshot(
                        token_id,
                        condition_id,
                        *depth[token_id],
                    )
                    if snapshot is not None:
                        yield snapshot
                    else:
                        depth.pop(token_id, None)
                    continue

                if not isinstance(event, MarketPriceChangeEvent):
                    continue
                condition_id = _identifier(event.payload.market)
                if condition_id is None:
                    continue
                pending_levels: dict[
                    str,
                    tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]],
                ] = {}
                invalid_tokens: set[str] = set()
                for change in event.payload.price_changes:
                    token_id = _identifier(change.token_id)
                    if token_id is None:
                        continue
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
                    levels = (
                        bid_ask_levels[0] if side is Side.BUY else bid_ask_levels[1]
                    )
                    if level.size == 0:
                        levels.pop(level.price, None)
                    else:
                        levels[level.price] = level.size
                for token_id, bid_ask_levels in pending_levels.items():
                    snapshot = self._snapshot(
                        token_id,
                        condition_id,
                        *bid_ask_levels,
                    )
                    if snapshot is not None:
                        depth[token_id] = bid_ask_levels
                        yield snapshot

    def _resolution(
        self,
        event: MarketResolvedEvent,
    ) -> MarketResolutionEvent | None:
        payload = event.payload
        condition_id = _identifier(payload.market)
        if condition_id is None:
            return None
        market = self._market_by_condition.get(condition_id)
        token_ids = (
            None if payload.token_ids is None else _identifiers(payload.token_ids)
        )
        winning_token_id = _identifier(payload.winning_token_id)
        if (
            market is None
            or token_ids is None
            or len(token_ids) != 2
            or set(token_ids) != {market.yes_token_id, market.no_token_id}
            or winning_token_id not in token_ids
            or normalize_outcome(payload.winning_outcome) is None
        ):
            return None
        normalized_payload_outcome = normalize_outcome(payload.winning_outcome)
        expected_outcome = outcome_label_for_token(market, winning_token_id)
        if expected_outcome is None or expected_outcome != normalized_payload_outcome:
            return None
        resolved_at_ms = self._now_ms()
        if payload.timestamp is not None:
            try:
                resolved_at_ms = int(payload.timestamp.timestamp() * 1_000)
            except (AttributeError, OverflowError, OSError, ValueError):
                return None
        return MarketResolutionEvent(
            condition_id=condition_id,
            market_slug=market.slug,
            token_ids=(market.yes_token_id, market.no_token_id),
            winning_token_id=winning_token_id,
            winning_outcome=expected_outcome,
            resolved_at_ms=resolved_at_ms,
            source=MARKET_WEBSOCKET_SOURCE,
        )

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
                outcome=outcome_label_for_token(market, token_id) if market else None,
                expected_token_id=token_id,
                expected_condition_id=market.condition_id if market else None,
            )
        except MarketDataError:
            return None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()


def _normalize_price_change_side(raw_side: object) -> Side:
    try:
        return Side(raw_side)
    except (TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_SIDE,
            "price change side is invalid",
        ) from error


def _identifier(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _identifiers(values: object) -> tuple[str, ...] | None:
    if not isinstance(values, (tuple, list)):
        return None
    identifiers = tuple(_identifier(value) for value in values)
    if any(identifier is None for identifier in identifiers):
        return None
    return tuple(identifier for identifier in identifiers if identifier is not None)
