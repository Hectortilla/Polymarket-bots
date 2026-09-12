"""Exact market identifiers must resolve to validated canonical selections."""

import asyncio
from http import HTTPStatus
from unittest.mock import AsyncMock, Mock

import pytest
from polymarket import RequestRejectedError
from polymarket.pagination import Page
from polybot.polymarket.discovery import MarketDiscovery
from polybot.polymarket.errors import MarketDataError, MarketDataTransportError
from sdk_market_fixture import sdk_market


def numeric_client(**kwargs):
    client = Mock(**kwargs)
    client.list_markets.return_value.first_page = AsyncMock(
        return_value=Page(items=(), has_more=False)
    )
    return client


def test_numeric_market_id_uses_exact_lookup_and_returns_slug():
    market = sdk_market("canonical").model_copy(update={"id": "123"})
    client = numeric_client(get_market=AsyncMock(return_value=market))
    result = asyncio.run(MarketDiscovery(client).search("123", 12))
    assert result.markets[0].slug == "canonical"
    client.get_market.assert_awaited_once_with(id="123")
    client.search.assert_not_called()


@pytest.mark.parametrize("kind", ["condition", "token"])
def test_condition_and_token_ids_use_exact_sdk_filters(kind):
    query = (
        "0x" + "ab" * 32 if kind == "condition" else "123456789012345678901234567890"
    )
    source = sdk_market("canonical", no_token_id=query)
    source = source.model_copy(
        update={"condition_id": query if kind == "condition" else source.condition_id}
    )
    client = Mock(
        get_market=AsyncMock(
            side_effect=RequestRejectedError("missing", status=HTTPStatus.NOT_FOUND)
        )
    )
    client.list_markets.return_value.first_page = AsyncMock(
        return_value=Page(items=(source,), has_more=False)
    )
    result = asyncio.run(MarketDiscovery(client).search(query, 12))
    assert result.markets[0].slug == "canonical"
    filters = {
        "condition_ids" if kind == "condition" else "clob_token_ids": (query,),
        "page_size": 2,
    }
    client.list_markets.assert_called_once_with(**filters)
    client.search.assert_not_called()
    client.get_market.assert_not_called()


@pytest.mark.parametrize("state", [{"closed": True}, {"archived": True}])
def test_exact_id_never_offers_unavailable_markets(state):
    source = sdk_market("canonical").model_copy(update={"id": "123"})
    source = source.model_copy(update={"state": source.state.model_copy(update=state)})
    result = asyncio.run(
        MarketDiscovery(
            numeric_client(get_market=AsyncMock(return_value=source))
        ).search("123", 12)
    )
    assert result.markets == ()


def test_wrong_numeric_identity_fails_closed():
    client = numeric_client(get_market=AsyncMock(return_value=sdk_market("wrong")))
    with pytest.raises(MarketDataError):
        asyncio.run(MarketDiscovery(client).search("123", 12))


@pytest.mark.parametrize(
    "items, has_more",
    [
        ((), True),
        ((sdk_market("wrong"),), False),
        ((sdk_market("one"), sdk_market("two")), False),
    ],
)
def test_wrong_or_ambiguous_condition_identity_fails_closed(items, has_more):
    client = Mock()
    client.list_markets.return_value.first_page = AsyncMock(
        return_value=Page(items=items, has_more=has_more)
    )
    with pytest.raises(MarketDataError):
        asyncio.run(MarketDiscovery(client).search("0x" + "ab" * 32, 12))


def test_missing_identifier_returns_empty_result():
    client = Mock(
        get_market=AsyncMock(
            side_effect=RequestRejectedError("missing", status=HTTPStatus.NOT_FOUND)
        )
    )
    client.list_markets.return_value.first_page = AsyncMock(
        return_value=Page(items=(), has_more=False)
    )
    assert asyncio.run(MarketDiscovery(client).search("123", 12)).markets == ()


def test_exact_lookup_transport_failure_is_not_missing_market():
    client = numeric_client(get_market=AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(MarketDataTransportError):
        asyncio.run(MarketDiscovery(client).search("123", 12))
