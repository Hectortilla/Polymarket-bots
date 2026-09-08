"""Market-plan resolution for the paper runner."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from polybot.framework.streams import StreamPlan
from polybot.polymarket.markets import Market


class MarketResolver(Protocol):
    async def find_many(self, slugs: Iterable[str]) -> tuple[Market | None, ...]: ...


@dataclass(frozen=True, slots=True)
class ResolvedMarketPlan:
    current: tuple[Market, ...]
    next: tuple[Market, ...]


async def resolve_plan_markets(
    plan: StreamPlan,
    gamma: MarketResolver,
) -> ResolvedMarketPlan:
    """Resolve current markets strictly and next markets best-effort."""
    current_slugs = plan.current_market_slugs
    next_slugs = plan.next_market_slugs

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
