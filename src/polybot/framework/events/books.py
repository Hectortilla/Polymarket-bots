from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from polybot.framework.events import Side, require_side
from polybot.framework.events.book_validation import BookValidationIssue
from polybot.framework.events.prices import is_outcome_price

BOOK_LEVEL_SIZE_FLOOR = Decimal("0")


class BookGapReason(StrEnum):
    """Stable reasons that invalidate one or more projected order books."""

    INVALID_MARKET_PARAMETERS = "invalid_market_parameters"
    INVALID_BOOK_LEVEL = "invalid_book_level"
    INVALID_BOOK_SIDE = "invalid_book_side"
    MISSING_BOOK_BASELINE = "missing_book_baseline"
    BOOK_IDENTITY_MISMATCH = "book_identity_mismatch"
    BOOK_STREAM_GAP = "book_stream_gap"
    CROSSED_BOOK = "crossed_book"


@dataclass(frozen=True, slots=True)
class BookGapEvent:
    """A continuity loss after which prior book state is unsafe."""

    condition_id: str | None
    observed_at_ms: int
    reason: BookGapReason

    def __post_init__(self) -> None:
        if self.condition_id is not None and not self.condition_id:
            raise ValueError("book-gap condition ID must be non-empty")
        if self.observed_at_ms < 0:
            raise ValueError("book-gap timestamp must not be negative")
        if not isinstance(self.reason, BookGapReason):
            raise ValueError("book-gap reason must be a BookGapReason")

    def affects(self, condition_id: str | None) -> bool:
        """Return whether this gap invalidates the requested condition."""
        return self.condition_id is None or self.condition_id == condition_id


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    size: Decimal

    @property
    def notional_usdc(self) -> Decimal:
        return self.price * self.size

    def is_valid_price(self) -> bool:
        return is_outcome_price(self.price)

    def is_valid_size(self, *, allow_zero: bool = False) -> bool:
        try:
            lower_bound = BOOK_LEVEL_SIZE_FLOOR
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
            and self._has_unique_prices(self.bids)
            and self._has_unique_prices(self.asks)
        )

    @staticmethod
    def _has_unique_prices(levels: tuple[BookLevel, ...]) -> bool:
        return len({level.price for level in levels}) == len(levels)

    def is_crossed(self) -> bool:
        if not self.bids or not self.asks:
            return False
        return max(level.price for level in self.bids) > min(
            level.price for level in self.asks
        )

    def executable_levels(self, side: Side) -> tuple[BookLevel, ...]:
        require_side(side)
        if side is Side.BUY:
            return tuple(sorted(self.asks, key=lambda level: level.price))
        return tuple(sorted(self.bids, key=lambda level: level.price, reverse=True))

    def midpoint(self) -> Decimal | None:
        if not self.bids or not self.asks:
            return None
        return (
            max(level.price for level in self.bids)
            + min(level.price for level in self.asks)
        ) / 2

    def executable_mark(self, size: Decimal) -> Decimal | None:
        """Return the quote required to liquidate a non-zero position."""
        if size > 0 and self.bids:
            return max(level.price for level in self.bids)
        if size < 0 and self.asks:
            return min(level.price for level in self.asks)
        return None

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
