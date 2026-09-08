"""Normalize SDK search metadata using the runtime's market boundary."""

from polybot.polymarket.discovery_contracts import MarketSuggestion
from polybot.polymarket.normalization.market import normalize_market
from polybot.polymarket.normalization.values import validate_optional_text

from polymarket.models.gamma.market import Market as SdkMarket


def normalize_suggestion(
    source: SdkMarket,
    *,
    event_title: str | None = None,
) -> MarketSuggestion:
    market = normalize_market(source)
    return MarketSuggestion(
        slug=market.slug,
        condition_id=market.condition_id,
        question=market.question,
        event_title=validate_optional_text(event_title, "event title"),
        end_date=source.state.end_date,
        is_open_for_trading=market.is_open_for_trading
        and source.state.archived is not True,
    )
