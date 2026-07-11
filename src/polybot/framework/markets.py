from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


def market_bucket_slug(
    prefix: str,
    now_ms: int,
    bucket_seconds: int,
    *,
    bucket_offset: int = 0,
) -> str:
    """Build the canonical slug for a fixed-width Unix-time market bucket."""
    if not prefix.strip():
        raise ValueError("prefix must not be empty")
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    bucket_start = _market_bucket_start(now_ms, bucket_seconds, bucket_offset)
    return f"{prefix}-{bucket_start}"


def _market_bucket_start(now_ms: int, bucket_seconds: int, bucket_offset: int) -> int:
    return (now_ms // 1000 // bucket_seconds + bucket_offset) * bucket_seconds


class MarketSubscriptionRole(StrEnum):
    PRIMARY = "primary"


@dataclass(frozen=True, slots=True)
class MarketSubscription:
    slug: str
    role: MarketSubscriptionRole = MarketSubscriptionRole.PRIMARY
    activate_at_ms: int | None = None
    expire_at_ms: int | None = None

    @classmethod
    def from_slugs(cls, slugs: tuple[str, ...]) -> tuple[MarketSubscription, ...]:
        return tuple(cls(slug=slug) for slug in slugs)


@dataclass(frozen=True, slots=True)
class MarketPlan:
    current: tuple[MarketSubscription, ...]
    next: tuple[MarketSubscription, ...] = ()

    @property
    def active_slugs(self) -> frozenset[str]:
        return frozenset(market.slug for market in self.current)

    def accepts_slug(self, market_slug: str | None) -> bool:
        active_slugs = self.active_slugs
        if not active_slugs:
            return True
        return market_slug is not None and market_slug in active_slugs
