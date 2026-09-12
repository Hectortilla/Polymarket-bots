"""Normalized, test-only wallet discovery for account browser scenarios."""

from unittest.mock import AsyncMock

from polybot.polymarket.wallet_discovery import WalletDiscovery
from polybot.polymarket.wallet_discovery_contracts import (
    WalletSearchResults,
    WalletSuggestion,
)

BROWSER_WALLET = WalletSuggestion(address="0x" + "ab" * 20, name="Browser trader")


def browser_wallet_discovery():
    discovery = AsyncMock(spec=WalletDiscovery)
    discovery.search.return_value = WalletSearchResults((BROWSER_WALLET,), False)
    discovery.resolve.side_effect = lambda addresses: tuple(
        BROWSER_WALLET for address in addresses if address == BROWSER_WALLET.address
    )
    return discovery
