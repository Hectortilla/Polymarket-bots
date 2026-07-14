"""Normalization and enrichment for wallet-analysis rows."""

from collections.abc import Callable

from scripts.wallet_payloads import (
    ACTIVITY_SLUG_FIELD,
    CONDITION_ID_FIELD,
    ENRICHED_MARKET_SLUG_FIELD,
)


def enrich_activity_with_market_slug(
    activity: list[dict[str, object]],
    *,
    market_fetcher: Callable[[str], dict[str, object] | None] | None = None,
) -> list[dict[str, object]]:
    slug_cache: dict[str, str | None] = {}
    enriched: list[dict[str, object]] = []
    for item in activity:
        row = dict(item)
        slug = row.get(ENRICHED_MARKET_SLUG_FIELD) or row.get(ACTIVITY_SLUG_FIELD)
        condition_id = row.get(CONDITION_ID_FIELD)
        if (
            slug is None
            and market_fetcher is not None
            and isinstance(condition_id, str)
        ):
            if condition_id not in slug_cache:
                market = market_fetcher(condition_id)
                market_slug = market.get(ACTIVITY_SLUG_FIELD) if market else None
                slug_cache[condition_id] = (
                    market_slug if isinstance(market_slug, str) else None
                )
            slug = slug_cache[condition_id]
        if isinstance(slug, str):
            row[ENRICHED_MARKET_SLUG_FIELD] = slug
            row.setdefault(ACTIVITY_SLUG_FIELD, slug)
        enriched.append(row)
    return enriched
