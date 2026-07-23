"""Order-book payload contracts persisted in recordings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from polybot.framework.events import Side
from polybot.framework.events.prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
)

from .validation import (
    normalize_optional_text_fields,
    normalize_required_text_fields,
    validate_book_price,
    validate_decimal,
    validate_tick_size,
)

if TYPE_CHECKING:
    from polybot.framework.events.books import BookSnapshot


@dataclass(frozen=True, slots=True)
class RecordedBookLevel:
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        validate_book_price(self.price)
        validate_decimal(
            self.size,
            "book level size",
            minimum=Decimal("0"),
            minimum_inclusive=False,
        )


@dataclass(frozen=True, slots=True)
class BookBaselinePayload:
    token_id: str
    bids: tuple[RecordedBookLevel, ...]
    asks: tuple[RecordedBookLevel, ...]
    source_hash: str | None = None

    @classmethod
    def from_snapshot(cls, snapshot: BookSnapshot) -> BookBaselinePayload:
        """Convert a normalized order-book snapshot into a persisted baseline."""
        return cls(
            token_id=snapshot.token_id,
            bids=tuple(
                RecordedBookLevel(level.price, level.size) for level in snapshot.bids
            ),
            asks=tuple(
                RecordedBookLevel(level.price, level.size) for level in snapshot.asks
            ),
        )

    def __post_init__(self) -> None:
        normalize_required_text_fields(self, ("token_id",))
        normalize_optional_text_fields(self, ("source_hash",))
        for name in ("bids", "asks"):
            levels = getattr(self, name)
            if not isinstance(levels, tuple) or not all(
                isinstance(level, RecordedBookLevel) for level in levels
            ):
                raise ValueError(f"book {name} must be a tuple of book levels")
            prices = tuple(level.price for level in levels)
            if len(prices) != len(set(prices)):
                raise ValueError(f"book {name} contain duplicate price levels")


@dataclass(frozen=True, slots=True)
class BookChange:
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    source_hash: str | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None

    def __post_init__(self) -> None:
        normalize_required_text_fields(self, ("token_id",))
        normalize_optional_text_fields(self, ("source_hash",))
        if not isinstance(self.side, Side):
            raise ValueError("book change side is invalid")
        validate_book_price(self.price)
        validate_decimal(self.size, "book change size", minimum=Decimal("0"))
        for name in ("best_bid", "best_ask"):
            value = getattr(self, name)
            if value is not None:
                validate_decimal(
                    value,
                    name.replace("_", " "),
                    minimum=OUTCOME_PRICE_FLOOR,
                    maximum=OUTCOME_PRICE_CEILING,
                )


@dataclass(frozen=True, slots=True)
class TickSizeChangePayload:
    token_id: str
    old_tick_size: Decimal | None
    new_tick_size: Decimal

    def __post_init__(self) -> None:
        normalize_required_text_fields(self, ("token_id",))
        if self.old_tick_size is not None:
            validate_tick_size(self.old_tick_size, "old tick size")
        validate_tick_size(self.new_tick_size, "new tick size")


@dataclass(frozen=True, slots=True)
class BookDeltaPayload:
    changes: tuple[BookChange, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.changes, tuple)
            or not self.changes
            or not all(isinstance(change, BookChange) for change in self.changes)
        ):
            raise ValueError("book delta requires an ordered tuple of changes")
