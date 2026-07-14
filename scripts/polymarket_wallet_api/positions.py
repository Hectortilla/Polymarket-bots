"""SDK-backed position reads."""

from __future__ import annotations

from collections.abc import Callable
from itertools import islice

from polymarket import PublicClient
from polymarket.errors import PolymarketError

from .constants import (
    DEFAULT_MARKET_POSITION_LIMIT,
    DESCENDING_SORT,
    MARKET_POSITION_SORT_BY,
    MARKET_POSITION_STATUS,
    POSITION_SIZE_THRESHOLD,
    SDK_PAGE_SIZE,
)
from .sdk_payloads import position_payload
from .sdk_pagination import page_items
from scripts.wallet_payloads import normalize_position_rows


def fetch_positions(
    wallet: str,
    *,
    client_factory: Callable[[], PublicClient] = PublicClient,
) -> list[dict[str, object]]:
    try:
        with client_factory() as client:
            position_page = client.list_positions(
                user=wallet,
                size_threshold=POSITION_SIZE_THRESHOLD,
                page_size=SDK_PAGE_SIZE,
            ).first_page()
            position_models = page_items(position_page, context="SDK position")
    except (PolymarketError, ValueError):
        return []
    return normalize_position_rows(
        [position_payload(model) for model in position_models]
    )


def fetch_market_positions(
    condition_id: str,
    limit: int = DEFAULT_MARKET_POSITION_LIMIT,
    *,
    client_factory: Callable[[], PublicClient] = PublicClient,
) -> list[dict[str, object]]:
    if limit <= 0:
        raise ValueError("market position limit must be positive")
    with client_factory() as client:
        position_models = list(
            islice(
                client.list_market_positions(
                    market=condition_id,
                    status=MARKET_POSITION_STATUS,
                    sort_by=MARKET_POSITION_SORT_BY,
                    sort_direction=DESCENDING_SORT,
                    page_size=min(limit, SDK_PAGE_SIZE),
                ).iter_items(),
                limit,
            )
        )
    return normalize_position_rows(
        [
            position_payload(position)
            for model in position_models
            for position in model.positions
        ]
    )
