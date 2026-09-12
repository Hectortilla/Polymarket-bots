"""Wallet discovery ingress and launch configuration wiring."""

from unittest.mock import AsyncMock

import pytest
from api.catalog.definitions import CATALOG, NODE_BASED_DEFINITION_ID
from api.http.routes.paths import WALLET_SEARCH_PATH, WALLET_LOOKUP_PATH, api_route_path
from api.http.search_contracts import DEFAULT_DISCOVERY_SEARCH_LIMIT
from api.http.wallet_contracts import WALLET_DISCOVERY_UNAVAILABLE_DETAIL
from api.wallet_selection import MAX_SELECTED_WALLETS
from polybot.framework.streams import StreamRelation
from polybot.polymarket.wallet_discovery import WalletDiscovery, WalletDiscoveryError
from polybot.polymarket.wallet_discovery_contracts import (
    WalletSearchResults,
    WalletSuggestion,
)
from control_plane.auth_fixtures import authenticated_test_client as TestClient
from control_plane.auth_fixtures import create_authenticated_app as create_app

ADDRESS = "0x" + "ab" * 20


def test_wallet_endpoints_normalize_query_and_lookup_addresses():
    discovery = AsyncMock(spec=WalletDiscovery)
    discovery.search.return_value = WalletSearchResults(
        (WalletSuggestion(ADDRESS, "Trader"),), False
    )
    discovery.resolve.return_value = (WalletSuggestion(ADDRESS, "Trader"),)
    client = TestClient(create_app(wallet_discovery=discovery))
    response = client.get(
        api_route_path(WALLET_SEARCH_PATH), params={"q": "  Trader  "}
    )
    assert response.status_code == 200
    assert response.json()["wallets"] == [{"address": ADDRESS, "name": "Trader"}]
    discovery.search.assert_awaited_once_with("Trader", DEFAULT_DISCOVERY_SEARCH_LIMIT)
    response = client.post(
        api_route_path(WALLET_LOOKUP_PATH),
        json={
            "addresses": [ADDRESS, "  " + ADDRESS.upper().replace("0X", "0x") + "  "]
        },
    )
    assert response.status_code == 200
    discovery.resolve.assert_awaited_once_with((ADDRESS,))


@pytest.mark.parametrize(
    "body",
    [
        {"addresses": []},
        {"addresses": ["Trader"]},
        {"addresses": [ADDRESS] * (MAX_SELECTED_WALLETS + 1)},
        {"addresses": [ADDRESS], "extra": True},
    ],
)
def test_invalid_lookup_never_calls_upstream(body):
    discovery = AsyncMock(spec=WalletDiscovery)
    client = TestClient(create_app(wallet_discovery=discovery))
    assert client.post(api_route_path(WALLET_LOOKUP_PATH), json=body).status_code == 422
    discovery.resolve.assert_not_called()


def test_failure_is_safe_503():
    discovery = AsyncMock(spec=WalletDiscovery)
    discovery.search.side_effect = discovery.resolve.side_effect = WalletDiscoveryError(
        "private"
    )
    client = TestClient(create_app(wallet_discovery=discovery))
    responses = [
        client.get(api_route_path(WALLET_SEARCH_PATH), params={"q": "Trader"}),
        client.post(api_route_path(WALLET_LOOKUP_PATH), json={"addresses": [ADDRESS]}),
    ]
    for response in responses:
        assert response.status_code == 503
        assert response.json() == {"detail": WALLET_DISCOVERY_UNAVAILABLE_DETAIL}


def test_node_bot_wallets_reach_runtime_stream_rules_and_are_optional():
    entry = CATALOG[NODE_BASED_DEFINITION_ID]
    config = entry.parse_config(
        {
            "name": "Follow",
            "market_slugs": ["topic"],
            "wallet_addresses": [ADDRESS, ADDRESS.upper().replace("0X", "0x")],
        }
    )
    assert config.stream_rules[0].wallet_addresses == (ADDRESS,)
    assert config.to_bot_config().stream_rules == config.stream_rules
    assert config.stream_rules[0].relation == StreamRelation.INDEPENDENT
    assert config.stream_rules[0].accepts_trade(ADDRESS, "another-market")
    assert (
        entry.parse_config({"name": "Old config", "market_slugs": ["topic"]})
        .stream_rules[0]
        .wallet_addresses
        == ()
    )
