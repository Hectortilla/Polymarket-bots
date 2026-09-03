"""SDK-backed Gamma market reads."""

from __future__ import annotations

from collections.abc import Callable

from polymarket import PublicClient
from polymarket.errors import PolymarketError
from polybot.polymarket.wallet_activity.fields import (
    CONDITION_ID_FIELD,
    SDK_CONDITION_ID_ATTRIBUTE,
    SDK_SLUG_ATTRIBUTE,
)

from .market_contracts import SDK_CLOSED_ATTRIBUTE
from .market_payloads import market_payload
from .query_contracts import SINGLE_RESULT_PAGE_SIZE
from .sdk_pagination import page_items


def gamma_condition_id(
    slug: str,
    *,
    client_factory: Callable[[], PublicClient] = PublicClient,
) -> tuple[str | None, bool | None]:
    try:
        with client_factory() as client:
            event_page = client.list_events(
                slug=slug,
                page_size=SINGLE_RESULT_PAGE_SIZE,
            ).first_page()
            events = page_items(event_page, context="SDK Gamma")
    except (PolymarketError, ValueError):
        return None, None
    if not events:
        return None, None
    event = events[0]
    if getattr(event, SDK_SLUG_ATTRIBUTE, None) != slug:
        return None, None
    market = event.markets[0] if event.markets else None
    closed = getattr(event.state, SDK_CLOSED_ATTRIBUTE, None)
    condition_id = (
        getattr(market, SDK_CONDITION_ID_ATTRIBUTE, None) if market else None
    )
    return str(condition_id) if condition_id else None, closed


def fetch_gamma_market(
    condition_id: str,
    *,
    client_factory: Callable[[], PublicClient] = PublicClient,
) -> dict[str, object] | None:
    try:
        with client_factory() as client:
            market_page = client.list_markets(
                condition_ids=condition_id,
                page_size=SINGLE_RESULT_PAGE_SIZE,
            ).first_page()
            markets = page_items(market_page, context="SDK Gamma")
    except (PolymarketError, ValueError):
        return None
    if not markets:
        return None
    payload = market_payload(markets[0])
    return payload if payload.get(CONDITION_ID_FIELD) == condition_id else None
