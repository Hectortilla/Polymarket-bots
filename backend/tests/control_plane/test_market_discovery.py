import asyncio
from dataclasses import asdict

import pytest
from api.catalog.inputs import NodeBasedLaunchInputs
from api.http.app import create_app
from api.http.market_contracts import (
    DEFAULT_MARKET_SEARCH_LIMIT,
    MARKET_DISCOVERY_UNAVAILABLE_DETAIL,
    MAX_MARKET_SEARCH_LENGTH,
    MAX_MARKET_SEARCH_LIMIT,
)
from api.http.routes.bots.market_validation import (
    validate_new_market_selections,
)
from api.http.routes.paths import (
    MARKET_LOOKUP_PATH,
    MARKET_SEARCH_PATH,
    api_route_path,
)
from api.market_selection import MAX_SELECTED_MARKETS
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from polybot.polymarket.discovery_contracts import MarketSearchResults
from polybot.polymarket.errors import MarketDataTransportError

from control_plane.market_fixtures import market_discovery, market_suggestion


def test_search_normalizes_query_and_returns_typed_markets() -> None:
    discovery = market_discovery()
    market = market_suggestion("election")
    discovery.search.return_value = MarketSearchResults((market,), False)
    client = TestClient(create_app(market_discovery=discovery))

    response = client.get(
        api_route_path(MARKET_SEARCH_PATH), params={"q": "  election  "}
    )

    assert response.status_code == 200
    assert response.json() == {"markets": [asdict(market)], "has_more": False}
    discovery.search.assert_awaited_once_with("election", DEFAULT_MARKET_SEARCH_LIMIT)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": " "},
        {"q": "x"},
        {"q": "x" * (MAX_MARKET_SEARCH_LENGTH + 1)},
        {"q": "abc", "limit": 0},
        {"q": "abc", "limit": MAX_MARKET_SEARCH_LIMIT + 1},
        {"q": "abc", "limit": "1.5"},
        {"q": "abc", "unknown": "true"},
    ],
)
def test_invalid_queries_do_not_call_upstream(params) -> None:
    discovery = market_discovery()
    client = TestClient(create_app(market_discovery=discovery))
    assert (
        client.get(api_route_path(MARKET_SEARCH_PATH), params=params).status_code == 422
    )
    discovery.search.assert_not_called()


def test_lookup_trims_deduplicates_and_preserves_closed_markets() -> None:
    discovery = market_discovery()
    market = market_suggestion("closed", available=False)
    discovery.resolve.side_effect = None
    discovery.resolve.return_value = (market,)
    client = TestClient(create_app(market_discovery=discovery))
    response = client.post(
        api_route_path(MARKET_LOOKUP_PATH),
        json={"slugs": [" closed ", "closed", "missing"]},
    )
    assert response.status_code == 200
    assert response.json() == [asdict(market)]
    discovery.resolve.assert_awaited_once_with(("closed", "missing"))


@pytest.mark.parametrize(
    "body",
    [
        {"slugs": []},
        {"slugs": [""]},
        {"slugs": [1]},
        {"slugs": ["a"] * (MAX_SELECTED_MARKETS + 1)},
        {"slugs": ["a"], "extra": True},
    ],
)
def test_lookup_rejects_invalid_payload(body) -> None:
    discovery = market_discovery()
    client = TestClient(create_app(market_discovery=discovery))
    assert client.post(api_route_path(MARKET_LOOKUP_PATH), json=body).status_code == 422
    discovery.resolve.assert_not_called()


def test_discovery_failure_returns_safe_service_unavailable() -> None:
    discovery = market_discovery()
    discovery.search.side_effect = MarketDataTransportError("private upstream detail")
    discovery.resolve.side_effect = discovery.search.side_effect
    client = TestClient(create_app(market_discovery=discovery))
    responses = (
        client.get(api_route_path(MARKET_SEARCH_PATH), params={"q": "topic"}),
        client.post(api_route_path(MARKET_LOOKUP_PATH), json={"slugs": ["topic"]}),
    )
    for response in responses:
        assert response.status_code == 503
        assert response.json() == {"detail": MARKET_DISCOVERY_UNAVAILABLE_DETAIL}


def test_save_validates_only_new_selections_and_preserves_old_ones() -> None:
    discovery = market_discovery()
    previous = NodeBasedLaunchInputs(name="test", market_slugs=("old",)).to_run_config()
    current = NodeBasedLaunchInputs(
        name="test", market_slugs=("old", "new")
    ).to_run_config()
    asyncio.run(validate_new_market_selections(previous, discovery, previous=previous))
    discovery.resolve.assert_not_called()
    asyncio.run(validate_new_market_selections(current, discovery, previous=previous))
    discovery.resolve.assert_awaited_once_with(("new",))


@pytest.mark.parametrize("resolved", [(), (market_suggestion("new", available=False),)])
def test_save_rejects_missing_or_closed_new_selection(resolved) -> None:
    discovery = market_discovery()
    discovery.resolve.side_effect = None
    discovery.resolve.return_value = resolved
    config = NodeBasedLaunchInputs(name="test", market_slugs=("new",)).to_run_config()
    with pytest.raises(RequestValidationError) as failure:
        asyncio.run(validate_new_market_selections(config, discovery))
    assert failure.value.errors()[0]["loc"][-1] == "market_slugs"


def test_save_fails_closed_when_lookup_is_unavailable() -> None:
    discovery = market_discovery()
    discovery.resolve.side_effect = MarketDataTransportError("offline")
    config = NodeBasedLaunchInputs(name="test", market_slugs=("new",)).to_run_config()
    with pytest.raises(HTTPException) as failure:
        asyncio.run(validate_new_market_selections(config, discovery))
    assert failure.value.status_code == 503
