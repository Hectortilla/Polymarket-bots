"""Normalized Polymarket market contracts and indexing."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from polybot.polymarket.errors import MarketDataError, MarketDataIssue


@dataclass(frozen=True, slots=True)
class MarketOutcome:
    label: str
    token_id: str


@dataclass(frozen=True, slots=True)
class Market:
    condition_id: str
    slug: str
    question: str
    minimum_tick_size: Decimal | None
    minimum_order_size: Decimal | None
    neg_risk: bool
    fee_rate: Decimal
    outcomes: tuple[MarketOutcome, MarketOutcome]
    resolved: bool = False
    winning_token_id: str | None = None
    winning_outcome: str | None = None

    @property
    def token_ids(self) -> tuple[str, str]:
        return self.outcomes[0].token_id, self.outcomes[1].token_id

    def token_id_for_outcome(self, label: str) -> str | None:
        normalized = label.casefold().strip()
        matches = [
            outcome.token_id
            for outcome in self.outcomes
            if outcome.label.casefold().strip() == normalized
        ]
        return matches[0] if matches and len(set(matches)) == 1 else None

    def outcome_label_for_token(self, token_id: str) -> str | None:
        for outcome in self.outcomes:
            if outcome.token_id == token_id:
                return outcome.label
        return None


def index_markets_by_token(markets: Iterable[Market]) -> dict[str, Market]:
    indexed: dict[str, Market] = {}
    for market in markets:
        for token_id in market.token_ids:
            previous = indexed.get(token_id)
            if previous is not None and previous != market:
                raise MarketDataError(
                    MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                    f"token ID maps to multiple markets: {token_id}",
                )
            indexed[token_id] = market
    return indexed
