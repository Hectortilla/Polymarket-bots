from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from polybot.framework.events.book_validation import BookValidationIssue


if TYPE_CHECKING:
    from polybot.framework.events import Side

PRICE_FLOOR = Decimal("0")
PRICE_CEILING = Decimal("1")
BOOK_LEVEL_VALUE_FLOOR = PRICE_FLOOR
BOOK_PRICE_CEILING = PRICE_CEILING


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    size: Decimal

    @property
    def notional_usdc(self) -> Decimal:
        return self.price * self.size

    def is_valid_price(self) -> bool:
        try:
            return (
                self.price.is_finite()
                and PRICE_FLOOR < self.price <= PRICE_CEILING
            )
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return False

    def is_valid_size(self, *, allow_zero: bool = False) -> bool:
        try:
            lower_bound = BOOK_LEVEL_VALUE_FLOOR
            return self.size.is_finite() and (
                self.size >= lower_bound if allow_zero else self.size > lower_bound
            )
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return False

    def is_valid(self) -> bool:
        return self.is_valid_price() and self.is_valid_size()


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    token_id: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    received_at_ms: int
    market_slug: str | None = None
    condition_id: str | None = None
    outcome: str | None = None

    def is_fresh(self, now_ms: int, max_age_ms: int) -> bool:
        age_ms = now_ms - self.received_at_ms
        return 0 <= age_ms <= max_age_ms

    def has_valid_levels(self) -> bool:
        return (
            isinstance(self.bids, tuple)
            and isinstance(self.asks, tuple)
            and all(
                isinstance(level, BookLevel) and level.is_valid()
                for level in (*self.bids, *self.asks)
            )
        )

    def is_crossed(self) -> bool:
        if not self.bids or not self.asks:
            return False
        return max(level.price for level in self.bids) > min(
            level.price for level in self.asks
        )

    def executable_levels(self, side: Side) -> tuple[BookLevel, ...]:
        from polybot.framework.events import Side

        if side is Side.BUY:
            return tuple(sorted(self.asks, key=lambda level: level.price))
        return tuple(sorted(self.bids, key=lambda level: level.price, reverse=True))

    def validation_issue(
        self,
        now_ms: int,
        max_age_ms: int,
    ) -> BookValidationIssue | None:
        if self.received_at_ms > now_ms:
            return BookValidationIssue.FUTURE_DATED
        if not self.is_fresh(now_ms, max_age_ms):
            return BookValidationIssue.STALE
        if not self.has_valid_levels():
            return BookValidationIssue.BAD_LEVEL
        if self.is_crossed():
            return BookValidationIssue.CROSSED
        return None
