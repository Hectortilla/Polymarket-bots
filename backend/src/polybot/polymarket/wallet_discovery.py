"""Bounded public profile discovery through the official async SDK."""

import asyncio
import logging

from polybot.framework.wallets import WALLET_ADDRESS_PATTERN
from polybot.polymarket.client_lifecycle import PublicClientLease
from polybot.polymarket.discovery_policy import DISCOVERY_TIMEOUT_SECONDS
from polybot.polymarket.normalization.wallet_discovery import (
    normalize_wallet_suggestion,
)
from polybot.polymarket.wallet_discovery_contracts import (
    WalletSearchResults,
    WalletSuggestion,
)
from polymarket import AsyncPublicClient, PolymarketError

logger = logging.getLogger(__name__)


class WalletDiscoveryError(RuntimeError):
    """Public profile discovery failed or returned unusable identity data."""


class WalletDiscovery:
    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._lease = PublicClientLease.acquire(client)

    async def search(self, query: str, limit: int) -> WalletSearchResults:
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS):
                if WALLET_ADDRESS_PATTERN.fullmatch(query):
                    choice = await self._resolve_address(query.lower())
                    return WalletSearchResults((choice,), False)
                page = await self._lease.client.search(
                    q=query,
                    search_profiles=True,
                    search_tags=False,
                    page_size=limit,
                ).first_page()
                suggestions: dict[str, WalletSuggestion] = {}
                for result in page.items:
                    for profile in result.profiles:
                        try:
                            choice = normalize_wallet_suggestion(profile)
                        except ValueError:
                            logger.warning(
                                "Skipping wallet search result without valid identity"
                            )
                            continue
                        # Names are presentation metadata; the trading address is identity.
                        suggestions.setdefault(choice.address, choice)
                choices = tuple(suggestions.values())
                return WalletSearchResults(
                    choices[:limit], page.has_more or len(choices) > limit
                )
        except (PolymarketError, TimeoutError, ValueError) as error:
            raise WalletDiscoveryError("wallet search unavailable") from error

    async def resolve(self, addresses: tuple[str, ...]) -> tuple[WalletSuggestion, ...]:
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS):
                choices = await asyncio.gather(
                    *(self._resolve_address(address) for address in addresses)
                )
                # Hydration must never silently change a saved address to another wallet.
                return tuple(
                    choice
                    if choice.address == address
                    else WalletSuggestion(address, None)
                    for address, choice in zip(addresses, choices, strict=True)
                )
        except (PolymarketError, TimeoutError, ValueError) as error:
            raise WalletDiscoveryError("wallet lookup unavailable") from error

    async def close(self) -> None:
        await self._lease.close()

    async def _resolve_address(self, address: str) -> WalletSuggestion:
        profile = await self._lease.client.get_public_profile(address)
        if profile is None:
            # An explicit address remains selectable without a public profile.
            return WalletSuggestion(address, None)
        return normalize_wallet_suggestion(profile)
