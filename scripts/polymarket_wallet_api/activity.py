"""SDK-backed wallet activity reads."""

from __future__ import annotations

from collections.abc import Callable

from polymarket import PublicClient
from polymarket.errors import PolymarketError

from .constants import (
    ACTIVITY_SORT_BY,
    DESCENDING_SORT,
    MAX_ACTIVITY_ITEMS,
    MAX_ACTIVITY_OFFSET,
    SDK_PAGE_SIZE,
)
from .normalization import enrich_activity_with_market_slug
from .sdk_payloads import activity_payload
from scripts.wallet_payloads import normalize_activity_rows


def fetch_all_activity(
    wallet: str,
    max_items: int | None = None,
    *,
    client_factory: Callable[[], PublicClient] = PublicClient,
    enrich: Callable[
        [list[dict[str, object]]], list[dict[str, object]]
    ] = enrich_activity_with_market_slug,
) -> tuple[list[dict[str, object]], bool]:
    item_limit = MAX_ACTIVITY_ITEMS if max_items is None else max_items
    with client_factory() as client:
        paginator = client.list_activity(
            user=wallet,
            sort_by=ACTIVITY_SORT_BY,
            sort_direction=DESCENDING_SORT,
            page_size=SDK_PAGE_SIZE,
        )
        activity_models: list[object] = []
        truncated = False
        try:
            model_iterator = iter(paginator.iter_items())
            for _ in range(item_limit + 1):
                activity_models.append(next(model_iterator))
        except StopIteration:
            pass
        except PolymarketError as exc:
            if not _is_activity_offset_limit_error(exc):
                raise
            truncated = True
        else:
            truncated = len(activity_models) > item_limit
    if len(activity_models) > item_limit:
        activity_models = activity_models[:item_limit]
        truncated = True
    elif len(activity_models) >= MAX_ACTIVITY_OFFSET:
        truncated = True
    rows = normalize_activity_rows(
        [activity_payload(model) for model in activity_models]
    )
    return enrich([dict(row) for row in rows]), truncated


def _is_activity_offset_limit_error(error: PolymarketError) -> bool:
    return (
        f"max historical activity offset of {MAX_ACTIVITY_OFFSET} exceeded"
        in str(error).lower()
    )
