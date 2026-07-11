from __future__ import annotations

from itertools import islice
from typing import Final

from polymarket import PublicClient
from polymarket.errors import PolymarketError

from scripts.polymarket_wallet_api.sdk_payloads import activity_payload, market_payload, position_payload
from scripts.wallet_payloads import CONDITION_ID_FIELD, normalize_activity_rows, normalize_position_rows

GAMMA_API_BASE: Final = "https://gamma-api.polymarket.com"
GAMMA_MARKETS_PATH: Final = "/markets"
MAX_ACTIVITY_ITEMS: Final = 3_500
MAX_ACTIVITY_OFFSET: Final = 3_000
SDK_PAGE_SIZE: Final = 500
POSITION_SIZE_THRESHOLD: Final = 0.1
SINGLE_RESULT_PAGE_SIZE: Final = 1
DEFAULT_MARKET_POSITION_LIMIT: Final = SDK_PAGE_SIZE
ACTIVITY_SORT_BY: Final = "TIMESTAMP"
DESCENDING_SORT: Final = "DESC"
MARKET_POSITION_STATUS: Final = "ALL"
MARKET_POSITION_SORT_BY: Final = "TOKENS"


def fetch_all_activity(
    wallet: str,
    max_items: int | None = None,
) -> tuple[list[dict[str, object]], bool]:
    item_limit = max_items or MAX_ACTIVITY_ITEMS
    with PublicClient() as client:
        paginator = client.list_activity(
            user=wallet,
            sort_by=ACTIVITY_SORT_BY,
            sort_direction=DESCENDING_SORT,
            page_size=SDK_PAGE_SIZE,
        )
        models = []
        truncated = False
        try:
            models_iterator = iter(paginator.iter_items())
            for _ in range(item_limit + 1):
                models.append(next(models_iterator))
        except StopIteration:
            pass
        except PolymarketError as exc:
            if not _is_activity_offset_limit_error(exc):
                raise
            # The Data API rejects offsets >= 3000. Keep the rows already
            # fetched so one very active wallet does not abort the scan.
            truncated = True
        else:
            truncated = len(models) > item_limit
    if len(models) > item_limit:
        models = models[:item_limit]
        truncated = True
    elif len(models) >= MAX_ACTIVITY_OFFSET:
        truncated = True
    rows = normalize_activity_rows([activity_payload(model) for model in models])
    return enrich_activity_with_market_slug(rows), truncated


def _is_activity_offset_limit_error(error: PolymarketError) -> bool:
    return "max historical activity offset of 3000 exceeded" in str(error).lower()


def fetch_positions(wallet: str) -> list[dict[str, object]]:
    try:
        with PublicClient() as client:
            models = client.list_positions(
                user=wallet,
                size_threshold=POSITION_SIZE_THRESHOLD,
                page_size=SDK_PAGE_SIZE,
            ).first_page().items
    except PolymarketError:
        return []
    return normalize_position_rows([position_payload(model) for model in models])


def gamma_condition_id(slug: str) -> tuple[str | None, bool | None]:
    try:
        with PublicClient() as client:
            events = client.list_events(
                slug=slug,
                page_size=SINGLE_RESULT_PAGE_SIZE,
            ).first_page().items
    except PolymarketError:
        return None, None
    if not events:
        return None, None
    event = events[0]
    market = event.markets[0] if event.markets else None
    closed = getattr(event.state, "closed", None)
    return str(market.condition_id) if market and market.condition_id else None, closed


def fetch_market_positions(
    condition_id: str,
    limit: int = DEFAULT_MARKET_POSITION_LIMIT,
) -> list[dict[str, object]]:
    with PublicClient() as client:
        models = list(
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
            for model in models
            for position in model.positions
        ]
    )


def fetch_gamma_market(condition_id: str) -> dict[str, object] | None:
    try:
        with PublicClient() as client:
            markets = client.list_markets(
                condition_ids=condition_id,
                page_size=SINGLE_RESULT_PAGE_SIZE,
            ).first_page().items
    except PolymarketError:
        return None
    return market_payload(markets[0]) if markets else None


def enrich_activity_with_market_slug(
    activity: list[dict[str, object]],
) -> list[dict[str, object]]:
    slug_cache: dict[str, str | None] = {}
    enriched = []
    for item in activity:
        row = dict(item)
        slug = row.get("market_slug") or row.get("slug")
        condition_id = row.get(CONDITION_ID_FIELD)
        if slug is None and isinstance(condition_id, str):
            if condition_id not in slug_cache:
                market = fetch_gamma_market(condition_id)
                market_slug = market.get("slug") if market else None
                slug_cache[condition_id] = market_slug if isinstance(market_slug, str) else None
            slug = slug_cache[condition_id]
        if isinstance(slug, str):
            row["market_slug"] = slug
            row.setdefault("slug", slug)
        enriched.append(row)
    return enriched
