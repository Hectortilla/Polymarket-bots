"""Authoritative request constraints for control-plane market discovery."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from api.market_selection import MAX_SELECTED_MARKETS, MarketSlug

MIN_MARKET_SEARCH_LENGTH = 2
MAX_MARKET_SEARCH_LENGTH = 200
DEFAULT_MARKET_SEARCH_LIMIT = 12
MAX_MARKET_SEARCH_LIMIT = 20
MARKET_DISCOVERY_UNAVAILABLE_DETAIL = (
    "Market discovery is unavailable. Please try again."
)


class MarketSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=MIN_MARKET_SEARCH_LENGTH,
            max_length=MAX_MARKET_SEARCH_LENGTH,
        ),
    ]
    limit: int = Field(
        default=DEFAULT_MARKET_SEARCH_LIMIT, ge=1, le=MAX_MARKET_SEARCH_LIMIT
    )


class MarketLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slugs: tuple[MarketSlug, ...] = Field(min_length=1, max_length=MAX_SELECTED_MARKETS)
