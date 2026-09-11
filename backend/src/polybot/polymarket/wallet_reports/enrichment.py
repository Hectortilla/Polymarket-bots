"""Normalization and enrichment for wallet-analysis rows."""

from collections.abc import Callable

from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_SLUG_FIELD,
    CONDITION_ID_FIELD,
)
from polybot.polymarket.wallet_reports.contracts import ActivityRow
from polybot.polymarket.wallet_reports.fields import ENRICHED_MARKET_SLUG_FIELD

from .gamma import fetch_gamma_market
from .market_contracts import GammaMarketPayload


def enrich_activity_with_market_slug(
    activity: list[ActivityRow],
    *,
    market_fetcher: Callable[[str], GammaMarketPayload | None] = fetch_gamma_market,
) -> list[ActivityRow]:
    slug_cache: dict[str, str | None] = {}
    enriched: list[ActivityRow] = []
    for item in activity:
        row: ActivityRow = dict(item)  # type: ignore[assignment]
        slug = row.get(ENRICHED_MARKET_SLUG_FIELD) or row.get(ACTIVITY_SLUG_FIELD)
        condition_id = row.get(CONDITION_ID_FIELD)
        if slug is None and isinstance(condition_id, str):
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
