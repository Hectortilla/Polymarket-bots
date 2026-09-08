"""Normalized public-trade wake hints."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketTradeHint:
    condition_id: str
    token_id: str
    market_slug: str | None
    observed_at_ms: int
