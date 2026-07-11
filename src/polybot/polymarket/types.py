from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Iterable

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
    yes_token_id: str
    no_token_id: str
    minimum_tick_size: Decimal
    minimum_order_size: Decimal
    neg_risk: bool
    fee_rate: Decimal
    outcomes: tuple[MarketOutcome, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketTradeHint:
    condition_id: str
    token_id: str
    market_slug: str | None
    occurred_at_ms: int


@dataclass(frozen=True, slots=True)
class Position:
    token_id: str
    size: Decimal
    average_price: Decimal | None = None


def market_token_ids(market: Market) -> tuple[str, str]:
    return market.yes_token_id, market.no_token_id


def token_id_for_outcome(market: Market, label: str) -> str | None:
    normalized = label.casefold().strip()
    matches = [
        outcome.token_id
        for outcome in market.outcomes
        if outcome.label.casefold().strip() == normalized
    ]
    if matches:
        return matches[0] if len(set(matches)) == 1 else None
    return {"yes": market.yes_token_id, "no": market.no_token_id}.get(normalized)


def outcome_label_for_token(market: Market, token_id: str) -> str | None:
    for outcome in market.outcomes:
        if outcome.token_id == token_id:
            return outcome.label
    if token_id == market.yes_token_id:
        return "Yes"
    if token_id == market.no_token_id:
        return "No"
    return None


def index_markets_by_token(markets: Iterable[Market]) -> dict[str, Market]:
    indexed: dict[str, Market] = {}
    for market in markets:
        for token_id in market_token_ids(market):
            previous = indexed.get(token_id)
            if previous is not None and previous != market:
                raise MarketDataError(
                    MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                    f"token ID maps to multiple markets: {token_id}",
                )
            indexed[token_id] = market
    return indexed
