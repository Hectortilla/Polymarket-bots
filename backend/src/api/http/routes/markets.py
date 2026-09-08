"""Read-only market search and saved-selection metadata endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from polybot.polymarket.discovery_contracts import MarketSearchResults, MarketSuggestion
from polybot.polymarket.errors import MarketDataError, MarketDataTransportError

from api.http.dependencies import MarketDiscoveryDependency
from api.http.market_contracts import (
    MARKET_DISCOVERY_UNAVAILABLE_DETAIL,
    MarketLookupRequest,
    MarketSearchQuery,
)
from api.http.responses import SERVICE_UNAVAILABLE_RESPONSE
from api.http.routes.paths import (
    LOOKUP_MARKETS_OPERATION_ID,
    MARKET_LOOKUP_PATH,
    MARKET_SEARCH_PATH,
    SEARCH_MARKETS_OPERATION_ID,
)

router = APIRouter()


@router.get(
    MARKET_SEARCH_PATH,
    response_model=MarketSearchResults,
    operation_id=SEARCH_MARKETS_OPERATION_ID,
    responses=SERVICE_UNAVAILABLE_RESPONSE,
)
async def search_markets(
    query: Annotated[MarketSearchQuery, Query()],
    discovery: MarketDiscoveryDependency,
) -> MarketSearchResults:
    try:
        return await discovery.search(query.q, query.limit)
    except (MarketDataError, MarketDataTransportError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, MARKET_DISCOVERY_UNAVAILABLE_DETAIL
        ) from error


@router.post(
    MARKET_LOOKUP_PATH,
    response_model=list[MarketSuggestion],
    operation_id=LOOKUP_MARKETS_OPERATION_ID,
    responses=SERVICE_UNAVAILABLE_RESPONSE,
)
async def lookup_markets(
    request: MarketLookupRequest,
    discovery: MarketDiscoveryDependency,
) -> tuple[MarketSuggestion, ...]:
    try:
        return await discovery.resolve(tuple(dict.fromkeys(request.slugs)))
    except (MarketDataError, MarketDataTransportError) as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, MARKET_DISCOVERY_UNAVAILABLE_DETAIL
        ) from error
