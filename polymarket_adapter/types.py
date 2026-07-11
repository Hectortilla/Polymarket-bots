from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Iterable

from bots.polymarket.errors import MarketDataError, MarketDataIssue


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


@dataclass(frozen=True, slots=True)
class Position:
    token_id: str
    size: Decimal
    average_price: Decimal | None = None


def market_token_ids(market: Market) -> tuple[str, str]:
    return market.yes_token_id, market.no_token_id


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
