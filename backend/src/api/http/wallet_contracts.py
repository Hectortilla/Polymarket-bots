"""Bounded public wallet discovery requests."""

from pydantic import BaseModel, ConfigDict, Field

from api.http.search_contracts import DiscoverySearchQuery
from api.wallet_selection import MAX_SELECTED_WALLETS, WalletAddress

WALLET_DISCOVERY_UNAVAILABLE_DETAIL = (
    "Wallet discovery is unavailable. Please try again."
)


class WalletSearchQuery(DiscoverySearchQuery):
    pass


class WalletLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    addresses: tuple[WalletAddress, ...] = Field(
        min_length=1, max_length=MAX_SELECTED_WALLETS
    )
