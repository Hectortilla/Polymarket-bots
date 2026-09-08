from unittest.mock import AsyncMock

from polybot.polymarket.discovery import MarketDiscovery
from polybot.polymarket.discovery_contracts import MarketSuggestion


def market_suggestion(slug: str, *, available: bool = True) -> MarketSuggestion:
    return MarketSuggestion(
        slug=slug,
        condition_id=f"condition-{slug}",
        question=f"Will {slug} happen?",
        event_title=None,
        end_date=None,
        is_open_for_trading=available,
    )


def market_discovery() -> AsyncMock:
    discovery = AsyncMock(spec=MarketDiscovery)
    discovery.resolve.side_effect = lambda slugs: tuple(
        market_suggestion(slug) for slug in slugs
    )
    return discovery
