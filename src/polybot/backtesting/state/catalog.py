"""Normalized market metadata and replay lookup indexes."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from polybot.backtesting.contracts import BacktestError, BacktestFailureReason
from polybot.polymarket.markets import Market, MarketOutcome
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.payloads import ResolutionPayload


class MarketCatalog:
    """Own normalized replay markets and their immutable identity indexes."""

    def __init__(self) -> None:
        self._markets_by_condition: dict[str, Market] = {}
        self._condition_by_slug: dict[str, str] = {}
        self._condition_by_token: dict[str, str] = {}
        self._resolved_conditions: set[str] = set()

    @property
    def markets(self) -> tuple[Market, ...]:
        return tuple(self._markets_by_condition.values())

    @property
    def market_slugs(self) -> frozenset[str]:
        return frozenset(self._condition_by_slug)

    def add_metadata(self, payload: MarketMetadataPayload) -> Market:
        market = _market_from_metadata(payload)
        previous = self._markets_by_condition.get(market.condition_id)
        if previous is not None and (
            previous.slug != market.slug or previous.token_ids != market.token_ids
        ):
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                "recorded metadata changed immutable identity for "
                f"{market.condition_id}",
            )
        slug_condition = self._condition_by_slug.get(market.slug)
        if slug_condition is not None and slug_condition != market.condition_id:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"market slug maps to multiple recorded markets: {market.slug}",
            )
        for token_id in market.token_ids:
            existing = self._condition_by_token.get(token_id)
            if existing is not None and existing != market.condition_id:
                raise BacktestError(
                    BacktestFailureReason.MISSING_MARKET_DATA,
                    f"token ID maps to multiple recorded markets: {token_id}",
                )
        self._markets_by_condition[market.condition_id] = market
        self._condition_by_slug[market.slug] = market.condition_id
        for token_id in market.token_ids:
            self._condition_by_token[token_id] = market.condition_id
        if market.resolved:
            self._resolved_conditions.add(market.condition_id)
        return market

    def market_for_slug(self, slug: str) -> Market | None:
        condition_id = self._condition_by_slug.get(slug)
        return self.market_for_condition(condition_id)

    def market_for_condition(self, condition_id: str | None) -> Market | None:
        return (
            None
            if condition_id is None
            else self._markets_by_condition.get(condition_id)
        )

    def condition_for_token(self, token_id: str) -> str | None:
        return self._condition_by_token.get(token_id)

    def condition_for_slug(self, slug: str) -> str | None:
        return self._condition_by_slug.get(slug)

    def is_resolved(self, condition_id: str | None) -> bool:
        return condition_id in self._resolved_conditions

    def require_market(self, condition_id: str) -> Market:
        market = self.market_for_condition(condition_id)
        if market is None:
            raise BacktestError(
                BacktestFailureReason.MISSING_MARKET_DATA,
                f"recorded market metadata is missing for {condition_id}",
            )
        return market

    def update_tick_size(
        self,
        condition_id: str,
        new_tick_size: Decimal,
    ) -> None:
        market = self.require_market(condition_id)
        self._markets_by_condition[condition_id] = replace(
            market,
            minimum_tick_size=new_tick_size,
        )

    def resolve(
        self,
        condition_id: str,
        payload: ResolutionPayload,
    ) -> Market:
        market = self.require_market(condition_id)
        updated = replace(
            market,
            resolved=True,
            winning_token_id=payload.winning_token_id,
            winning_outcome=payload.winning_outcome,
        )
        self._markets_by_condition[condition_id] = updated
        self._resolved_conditions.add(condition_id)
        return updated


def _market_from_metadata(payload: MarketMetadataPayload) -> Market:
    return Market(
        condition_id=payload.condition_id,
        slug=payload.market_slug,
        question=payload.question,
        minimum_tick_size=payload.minimum_tick_size,
        minimum_order_size=payload.minimum_order_size,
        neg_risk=bool(payload.neg_risk),
        fee_rate=payload.fee_rate,
        outcomes=tuple(
            MarketOutcome(outcome.label, outcome.token_id)
            for outcome in payload.outcomes
        ),
        resolved=payload.resolved,
        winning_token_id=payload.winning_token_id,
        winning_outcome=payload.winning_outcome,
        active=payload.active,
        closed=payload.closed,
        order_book_enabled=payload.order_book_enabled,
        accepting_orders=payload.accepting_orders,
    )
