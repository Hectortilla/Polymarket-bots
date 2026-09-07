"""Package-owned market choices for discovery interfaces."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MarketSuggestion:
    slug: str
    condition_id: str
    question: str
    event_title: str | None
    end_date: datetime | None
    is_open_for_trading: bool


@dataclass(frozen=True, slots=True)
class MarketSearchResults:
    markets: tuple[MarketSuggestion, ...]
    has_more: bool
