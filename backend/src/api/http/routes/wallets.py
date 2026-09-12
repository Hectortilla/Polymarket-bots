"""Read-only wallet search and saved-selection metadata endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from polybot.polymarket.wallet_discovery_contracts import (
    WalletSearchResults,
    WalletSuggestion,
)
from polybot.polymarket.wallet_discovery import WalletDiscoveryError

from api.http.dependencies import WalletDiscoveryDependency
from api.http.wallet_contracts import (
    WALLET_DISCOVERY_UNAVAILABLE_DETAIL,
    WalletLookupRequest,
    WalletSearchQuery,
)
from api.http.responses import SERVICE_UNAVAILABLE_RESPONSE
from api.http.routes.paths import (
    LOOKUP_WALLETS_OPERATION_ID,
    WALLET_LOOKUP_PATH,
    WALLET_SEARCH_PATH,
    SEARCH_WALLETS_OPERATION_ID,
)

router = APIRouter()


@router.get(
    WALLET_SEARCH_PATH,
    response_model=WalletSearchResults,
    operation_id=SEARCH_WALLETS_OPERATION_ID,
    responses=SERVICE_UNAVAILABLE_RESPONSE,
)
async def search_wallets(
    query: Annotated[WalletSearchQuery, Query()],
    discovery: WalletDiscoveryDependency,
) -> WalletSearchResults:
    try:
        return await discovery.search(query.q, query.limit)
    except WalletDiscoveryError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, WALLET_DISCOVERY_UNAVAILABLE_DETAIL
        ) from error


@router.post(
    WALLET_LOOKUP_PATH,
    response_model=list[WalletSuggestion],
    operation_id=LOOKUP_WALLETS_OPERATION_ID,
    responses=SERVICE_UNAVAILABLE_RESPONSE,
)
async def lookup_wallets(
    request: WalletLookupRequest,
    discovery: WalletDiscoveryDependency,
) -> tuple[WalletSuggestion, ...]:
    try:
        return await discovery.resolve(tuple(dict.fromkeys(request.addresses)))
    except WalletDiscoveryError as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, WALLET_DISCOVERY_UNAVAILABLE_DETAIL
        ) from error
