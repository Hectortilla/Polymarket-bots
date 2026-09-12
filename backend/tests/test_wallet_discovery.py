"""Official SDK contracts for profile discovery and stable saved identities."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from polymarket import PolymarketError
from polymarket.models.gamma.profile import PublicProfile
from polymarket.models.gamma.search import Profile, SearchResults
from polymarket.pagination import Page
from polybot.polymarket.wallet_discovery import WalletDiscovery, WalletDiscoveryError
from polybot.polymarket.wallet_discovery_contracts import WalletSuggestion

ADDRESS = "0x" + "ab" * 20
OWNER = "0x" + "cd" * 20


def profile(**changes):
    return Profile.model_validate({"proxyWallet": ADDRESS, "name": "Trader", **changes})


def search_client(profiles, *, has_more=False):
    page = Page(
        items=(SearchResults.model_construct(profiles=tuple(profiles)),),
        has_more=has_more,
    )
    return Mock(search=Mock(return_value=Mock(first_page=AsyncMock(return_value=page))))


def test_search_uses_profile_search_and_normalizes_deduplicates_and_bounds():
    client = search_client(
        [
            profile(proxyWallet=ADDRESS.upper().replace("0X", "0x")),
            profile(),
            profile(proxyWallet=OWNER),
        ],
        has_more=True,
    )
    result = asyncio.run(WalletDiscovery(client).search("Trader", 1))
    assert result.wallets == (WalletSuggestion(ADDRESS, "Trader"),)
    assert result.has_more
    client.search.assert_called_once_with(
        q="Trader", search_profiles=True, search_tags=False, page_size=1
    )


def test_search_skips_missing_addresses_and_respects_hidden_display_names():
    client = search_client(
        [
            Profile.model_construct(wallet=None),
            profile(displayUsernamePublic=False, pseudonym="Public pseudonym"),
        ]
    )
    result = asyncio.run(WalletDiscovery(client).search("Public", 12))
    assert result.wallets == (WalletSuggestion(ADDRESS, "Public pseudonym"),)


def test_address_search_resolves_owner_to_trading_wallet_without_text_search():
    client = Mock(
        get_public_profile=AsyncMock(
            return_value=PublicProfile.model_validate(
                {"proxyWallet": ADDRESS, "name": "Trader"}
            )
        )
    )
    result = asyncio.run(WalletDiscovery(client).search(OWNER, 12))
    assert result.wallets == (WalletSuggestion(ADDRESS, "Trader"),)
    client.get_public_profile.assert_awaited_once_with(OWNER)
    client.search.assert_not_called()


def test_explicit_address_without_profile_is_selectable():
    client = Mock(get_public_profile=AsyncMock(return_value=None))
    result = asyncio.run(WalletDiscovery(client).search(ADDRESS, 12))
    assert result.wallets == (WalletSuggestion(ADDRESS, None),)


def test_saved_address_hydration_never_rewrites_configuration():
    client = Mock(
        get_public_profile=AsyncMock(
            return_value=PublicProfile.model_validate(
                {"proxyWallet": ADDRESS, "name": "Trader"}
            )
        )
    )
    result = asyncio.run(WalletDiscovery(client).resolve((OWNER, ADDRESS)))
    assert result == (
        WalletSuggestion(OWNER, None),
        WalletSuggestion(ADDRESS, "Trader"),
    )


@pytest.mark.parametrize("failure", [PolymarketError("private"), TimeoutError()])
def test_upstream_failures_are_not_empty_results_or_raw_address_fallback(failure):
    client = Mock(get_public_profile=AsyncMock(side_effect=failure))
    with pytest.raises(WalletDiscoveryError):
        asyncio.run(WalletDiscovery(client).search(ADDRESS, 12))
    with pytest.raises(WalletDiscoveryError):
        asyncio.run(WalletDiscovery(client).resolve((ADDRESS,)))


def test_malformed_exact_profile_fails_closed():
    client = Mock(
        get_public_profile=AsyncMock(
            return_value=PublicProfile.model_construct(wallet=None)
        )
    )
    with pytest.raises(WalletDiscoveryError):
        asyncio.run(WalletDiscovery(client).search(ADDRESS, 12))
