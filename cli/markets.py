"""Market-plan resolution for the paper runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from bots.framework.markets import MarketPlan
from bots.polymarket.types import Market

if TYPE_CHECKING:
    from bots.polymarket.gamma import GammaClient


@dataclass(frozen=True, slots=True)
class ResolvedMarketPlan:
    current: tuple[Market, ...]
    next: tuple[Market, ...]


async def resolve_plan_markets(
    plan: MarketPlan,
    gamma: GammaClient,
) -> ResolvedMarketPlan:
    """Resolve current markets strictly and next markets best-effort."""
    current_slugs = tuple(subscription.slug for subscription in plan.current)
    next_slugs = tuple(subscription.slug for subscription in plan.next)
    slugs = tuple(dict.fromkeys((*current_slugs, *next_slugs)))
    if not slugs:
        return ResolvedMarketPlan(current=(), next=())
    resolved = await gamma.find_many(slugs)
    by_slug = dict(zip(slugs, resolved))
    missing = [slug for slug in current_slugs if by_slug[slug] is None]
    if missing:
        raise RuntimeError(
            "configured markets could not be resolved: " + ", ".join(missing)
        )
    return ResolvedMarketPlan(
        current=tuple(by_slug[slug] for slug in current_slugs if by_slug[slug]),
        next=tuple(by_slug[slug] for slug in next_slugs if by_slug[slug]),
    )
