"""SDK-backed Gamma market reads."""

from __future__ import annotations

from collections.abc import Callable

from polymarket import PublicClient
from polymarket.errors import PolymarketError

from .constants import SINGLE_RESULT_PAGE_SIZE
from .sdk_payloads import market_payload
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
    market = event.markets[0] if event.markets else None
    closed = getattr(event.state, "closed", None)
    return str(market.condition_id) if market and market.condition_id else None, closed


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
    return market_payload(markets[0]) if markets else None
