"""Polymarket-owned resolution source contracts and conversion."""

from typing import Final

from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.markets import Market


GAMMA_RECONCILIATION_SOURCE: Final = "gamma_reconciliation"


def resolution_event_from_market(
    market: Market,
    *,
    resolved_at_ms: int,
    source: str,
) -> MarketResolutionEvent | None:
    """Build a source-independent event from resolved Gamma metadata."""
    if (
        not market.resolved
        or market.winning_token_id is None
        or market.winning_outcome is None
    ):
        return None
    return MarketResolutionEvent(
        condition_id=market.condition_id,
        market_slug=market.slug,
        token_ids=market.token_ids,
        winning_token_id=market.winning_token_id,
        winning_outcome=market.winning_outcome,
        resolved_at_ms=resolved_at_ms,
        source=source,
    )
