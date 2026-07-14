"""Paper-broker position discovery and market registration."""

from __future__ import annotations

from decimal import Decimal

from polybot.execution.paper import PaperBroker
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.types import Position

from ..market_identity import validate_position_market_identity
from ..tracked_markets import MarketInterest, TrackedMarketRegistry


async def track_paper_positions(
    paper_broker: PaperBroker,
    registry: TrackedMarketRegistry,
    gamma: GammaClient,
) -> None:
    portfolio = getattr(paper_broker, "portfolio", None)
    if portfolio is None:
        return
    position_tokens = set(portfolio.positions)
    if not position_tokens:
        return
    tracked_tokens: set[str] = set()
    for entry in registry.entries:
        market_tokens = (entry.market.yes_token_id, entry.market.no_token_id)
        tracked_tokens.update(market_tokens)
        if position_tokens.intersection(market_tokens):
            registry.add(entry.market, MarketInterest.BROKER_POSITION)
    refs = getattr(paper_broker, "position_market_refs", {})
    missing_refs = {
        token_id: refs[token_id]
        for token_id in position_tokens - tracked_tokens
        if token_id in refs
    }
    if not missing_refs:
        return
    slugs = tuple(dict.fromkeys(slug for slug, _ in missing_refs.values()))
    markets = await gamma.find_many(slugs)
    by_slug = {market.slug: market for market in markets if market is not None}
    for token_id, (slug, condition_id) in missing_refs.items():
        market = by_slug.get(slug)
        validate_position_market_identity(
            Position(
                token_id=token_id,
                size=Decimal("1"),
                condition_id=condition_id,
                market_slug=slug,
            ),
            market,
            "paper position has unresolved market identity",
        )
        registry.add(market, MarketInterest.BROKER_POSITION)
