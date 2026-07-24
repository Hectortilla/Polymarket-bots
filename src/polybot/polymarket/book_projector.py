"""Projection of normalized market-channel depth into framework books."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from polymarket.models.clob.order_book import OrderBookLevel

from polybot.framework.events import Side
from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.normalization.book import normalize_book
from polybot.polymarket.markets import (
    Market,
    index_markets_by_token,
)
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
)


type _DepthSides = tuple[dict[Decimal, Decimal], dict[Decimal, Decimal]]


class BookDepthProjector:
    """Own full depth and transactionally apply normalized channel messages."""

    def __init__(self, markets: Iterable[Market]) -> None:
        normalized = tuple(markets)
        self._market_by_token = index_markets_by_token(normalized)
        self._depth: dict[str, _DepthSides] = {}

    @property
    def baseline_token_ids(self) -> frozenset[str]:
        return frozenset(self._depth)

    def clear(self) -> None:
        """Forget projected depth while retaining immutable market identity."""
        self._depth.clear()

    def invalidate_condition(self, condition_id: str) -> None:
        """Forget depth made unreliable by a rejected update for one market."""
        invalid_token_ids = tuple(
            token_id
            for token_id in self._depth
            if self._market_by_token[token_id].condition_id == condition_id
        )
        for token_id in invalid_token_ids:
            del self._depth[token_id]

    def has_complete_baseline(self, condition_id: str) -> bool:
        """Whether every outcome token for one condition has projected depth."""
        token_ids = tuple(
            token_id
            for token_id, market in self._market_by_token.items()
            if market.condition_id == condition_id
        )
        return bool(token_ids) and set(token_ids).issubset(self._depth)

    def has_baselines(self, token_ids: Iterable[str]) -> bool:
        """Whether every requested token has a projected baseline."""
        required = frozenset(token_ids)
        return bool(required) and required.issubset(self._depth)

    def apply_baseline(
        self,
        payload: BookBaselinePayload,
        *,
        condition_id: str,
        received_at_ms: int,
    ) -> BookSnapshot:
        snapshot = self.preview_baseline(
            payload,
            condition_id=condition_id,
            received_at_ms=received_at_ms,
        )
        self._depth[payload.token_id] = self._depth_from_baseline(payload)
        return snapshot

    def preview_baseline(
        self,
        payload: BookBaselinePayload,
        *,
        condition_id: str,
        received_at_ms: int,
    ) -> BookSnapshot:
        """Validate and project a baseline without changing owned depth."""
        market = self._market_for(payload.token_id, condition_id)
        bids, asks = self._depth_from_baseline(payload)
        return self._snapshot(
            market,
            payload.token_id,
            bids,
            asks,
            received_at_ms=received_at_ms,
        )

    def apply_delta(
        self,
        payload: BookDeltaPayload,
        *,
        condition_id: str,
        received_at_ms: int,
    ) -> tuple[BookSnapshot, ...]:
        candidates: dict[str, _DepthSides] = {}
        for change in payload.changes:
            self._market_for(change.token_id, condition_id)
            current = self._depth.get(change.token_id)
            if current is None:
                raise MarketDataError(
                    MarketDataIssue.MISSING_BOOK_BASELINE,
                    f"price change arrived before a baseline for {change.token_id}",
                )
            candidate = candidates.setdefault(
                change.token_id,
                (current[0].copy(), current[1].copy()),
            )
            levels = candidate[0] if change.side is Side.BUY else candidate[1]
            if change.size == 0:
                levels.pop(change.price, None)
            else:
                levels[change.price] = change.size

        snapshots: list[BookSnapshot] = []
        for token_id, candidate in candidates.items():
            market = self._market_for(token_id, condition_id)
            snapshot = self._snapshot(
                market,
                token_id,
                *candidate,
                received_at_ms=received_at_ms,
            )
            snapshots.append(snapshot)

        for snapshot in snapshots:
            self._depth[snapshot.token_id] = candidates[snapshot.token_id]
        return tuple(snapshots)

    def snapshots(self, *, received_at_ms: int) -> tuple[BookSnapshot, ...]:
        return tuple(
            self._snapshot(
                self._market_by_token[token_id],
                token_id,
                *sides,
                received_at_ms=received_at_ms,
            )
            for token_id, sides in self._depth.items()
        )

    def condition_snapshots(
        self,
        condition_id: str,
        *,
        received_at_ms: int,
    ) -> tuple[BookSnapshot, ...]:
        """Project every available token book for one condition."""
        return tuple(
            self._snapshot(
                market,
                token_id,
                *self._depth[token_id],
                received_at_ms=received_at_ms,
            )
            for token_id, market in self._market_by_token.items()
            if market.condition_id == condition_id and token_id in self._depth
        )

    def _market_for(self, token_id: str, condition_id: str) -> Market:
        market = self._market_by_token.get(token_id)
        if market is None or market.condition_id != condition_id:
            raise MarketDataError(
                MarketDataIssue.BOOK_IDENTITY_MISMATCH,
                "market-channel identity does not match resolved metadata",
            )
        return market

    @staticmethod
    def _depth_from_baseline(payload: BookBaselinePayload) -> _DepthSides:
        return (
            {level.price: level.size for level in payload.bids},
            {level.price: level.size for level in payload.asks},
        )

    @staticmethod
    def _snapshot(
        market: Market,
        token_id: str,
        bids: dict[Decimal, Decimal],
        asks: dict[Decimal, Decimal],
        *,
        received_at_ms: int,
    ) -> BookSnapshot:
        return normalize_book(
            token_id=token_id,
            bids=tuple(
                OrderBookLevel(price=price, size=size) for price, size in bids.items()
            ),
            asks=tuple(
                OrderBookLevel(price=price, size=size) for price, size in asks.items()
            ),
            received_at_ms=received_at_ms,
            condition_id=market.condition_id,
            market_slug=market.slug,
            outcome=market.outcome_label_for_token(token_id),
            expected_token_id=token_id,
            expected_condition_id=market.condition_id,
        )
