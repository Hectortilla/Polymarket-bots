"""Paper-broker position discovery and market registration."""

from __future__ import annotations

from polybot.execution.paper import PaperBroker
from polybot.polymarket.gamma import GammaClient

from ..market_identity import validate_market_reference
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
    registrations = []
    for entry in registry.entries:
        market_tokens = entry.market.token_ids
        tracked_tokens.update(market_tokens)
        if position_tokens.intersection(market_tokens):
            registrations.append(entry.market)
    refs = getattr(paper_broker, "position_market_refs", {})
    missing_refs = {
        token_id: refs[token_id]
        for token_id in position_tokens - tracked_tokens
        if token_id in refs
    }
    if missing_refs:
        slugs = tuple(dict.fromkeys(slug for slug, _ in missing_refs.values()))
        markets = await gamma.find_many(slugs)
        by_slug = {market.slug: market for market in markets if market is not None}
        for token_id, (slug, condition_id) in missing_refs.items():
            market = by_slug.get(slug)
            validate_market_reference(
                market,
                token_id=token_id,
                condition_id=condition_id,
                market_slug=slug,
                error_message="paper position has unresolved market identity",
            )
            registrations.append(market)
    for market in registrations:
        registry.add(market, MarketInterest.BROKER_POSITION)
