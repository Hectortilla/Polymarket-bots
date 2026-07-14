"""Stable public wallet-analysis API adapters."""

from polymarket import PublicClient

from scripts.polymarket_wallet_api.constants import (
    DEFAULT_MARKET_POSITION_LIMIT,
)
from scripts.polymarket_wallet_api.activity import (
    fetch_all_activity as _fetch_all_activity,
)
from scripts.polymarket_wallet_api.gamma import (
    fetch_gamma_market as _fetch_gamma_market,
    gamma_condition_id as _gamma_condition_id,
)
from scripts.polymarket_wallet_api.positions import (
    fetch_market_positions as _fetch_market_positions,
    fetch_positions as _fetch_positions,
)
from scripts.polymarket_wallet_api.normalization import (
    enrich_activity_with_market_slug as _enrich_activity_with_market_slug,
)

__all__ = [
    "enrich_activity_with_market_slug",
    "fetch_all_activity",
    "fetch_gamma_market",
    "fetch_market_positions",
    "fetch_positions",
    "gamma_condition_id",
]


def fetch_all_activity(
    wallet: str,
    max_items: int | None = None,
) -> tuple[list[dict[str, object]], bool]:
    return _fetch_all_activity(
        wallet,
        max_items,
        client_factory=PublicClient,
        enrich=enrich_activity_with_market_slug,
    )


def fetch_positions(wallet: str) -> list[dict[str, object]]:
    return _fetch_positions(wallet, client_factory=PublicClient)


def gamma_condition_id(slug: str) -> tuple[str | None, bool | None]:
    return _gamma_condition_id(slug, client_factory=PublicClient)


def fetch_market_positions(
    condition_id: str,
    limit: int = DEFAULT_MARKET_POSITION_LIMIT,
) -> list[dict[str, object]]:
    return _fetch_market_positions(
        condition_id,
        limit,
        client_factory=PublicClient,
    )


def fetch_gamma_market(condition_id: str) -> dict[str, object] | None:
    return _fetch_gamma_market(condition_id, client_factory=PublicClient)


def enrich_activity_with_market_slug(
    activity: list[dict[str, object]],
) -> list[dict[str, object]]:
    return _enrich_activity_with_market_slug(
        activity,
        market_fetcher=fetch_gamma_market,
    )
