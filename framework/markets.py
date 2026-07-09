from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketSubscription:
    slug: str
    role: str = "primary"
    activate_at_ms: int | None = None
    expire_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class MarketPlan:
    current: tuple[MarketSubscription, ...]
    next: tuple[MarketSubscription, ...] = ()

    @property
    def active_slugs(self) -> frozenset[str]:
        return frozenset(market.slug for market in self.current)


def subscriptions_from_slugs(slugs: tuple[str, ...]) -> tuple[MarketSubscription, ...]:
    return tuple(MarketSubscription(slug=slug) for slug in slugs)
