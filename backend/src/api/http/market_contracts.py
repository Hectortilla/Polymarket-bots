"""Authoritative request constraints for control-plane market discovery."""

from pydantic import BaseModel, ConfigDict, Field

from api.market_selection import MAX_SELECTED_MARKETS, MarketSlug

from api.http.search_contracts import DiscoverySearchQuery

MARKET_DISCOVERY_UNAVAILABLE_DETAIL = (
    "Market discovery is unavailable. Please try again."
)


class MarketSearchQuery(DiscoverySearchQuery):
    pass


class MarketLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slugs: tuple[MarketSlug, ...] = Field(min_length=1, max_length=MAX_SELECTED_MARKETS)
