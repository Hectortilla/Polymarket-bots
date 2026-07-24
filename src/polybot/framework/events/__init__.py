from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from polybot.framework.events.book_validation import BookValidationIssue
from polybot.framework.events.prices import is_outcome_price


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


def require_side(side: Side) -> Side:
    """Return a validated order side for pure pricing and accounting helpers."""
    if not isinstance(side, Side):
        raise ValueError("side must be a Side")
    return side


class OrderStatus(StrEnum):
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELED = "canceled"


class FillRejectReason(StrEnum):
    MISSING_TOKEN_ID = "missing_token_id"
    BAD_SIDE = "bad_side"
    BAD_PRICE = "bad_price"
    BAD_SIZE = "bad_size"
    BOOK_UNAVAILABLE = "book_unavailable"
    BOOK_MISMATCH = "book_mismatch"
    BOOK_STALE = BookValidationIssue.STALE.value
    BOOK_FUTURE_DATED = BookValidationIssue.FUTURE_DATED.value
    BAD_BOOK_LEVEL = BookValidationIssue.BAD_LEVEL.value
    BOOK_CROSSED = BookValidationIssue.CROSSED.value
    MARKET_UNAVAILABLE = "market_unavailable"
    MARKET_FEE_INVALID = "market_fee_invalid"
    MARKET_METADATA_MISMATCH = "market_metadata_mismatch"
    MARKET_RESOLVED = "market_resolved"
    NO_DEPTH_WITHIN_SLIPPAGE = "no_depth_within_slippage"
    DUPLICATE_SOURCE_ID = "duplicate_source_id"
    INVALID_SOURCE_ID = "invalid_source_id"
    BACKTEST_DATA_EXHAUSTED = "backtest_data_exhausted"
    BACKTEST_COVERAGE_GAP = "backtest_coverage_gap"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    market_slug: str | None = None
    condition_id: str | None = None
    source_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class FillEvent:
    order_id: str
    token_id: str
    side: Side
    status: OrderStatus
    requested_size: Decimal
    filled_size: Decimal
    average_price: Decimal | None
    fee_usdc: Decimal
    received_at_ms: int
    reject_reason: FillRejectReason | None = None
    reject_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, OrderStatus):
            raise ValueError("fill status must be an OrderStatus")
        if self.received_at_ms < 0:
            raise ValueError("fill timestamp must not be negative")
        if self.status is OrderStatus.REJECTED:
            self._validate_order_id()
            self._validate_nonnegative_execution_amounts()
            if self.reject_reason is None:
                raise ValueError("Rejected fill events require a reject_reason.")
            if self.reject_message is None or not self.reject_message.strip():
                raise ValueError("Rejected fill events require a reject_message.")
            if (
                self.filled_size != 0
                or self.average_price is not None
                or self.fee_usdc != 0
            ):
                raise ValueError("rejected fills cannot contain execution values")
            return
        self._validate_identity()
        if not isinstance(self.side, Side):
            raise ValueError("fill side must be a Side")
        self._validate_amounts()
        if self.reject_reason is not None or self.reject_message is not None:
            raise ValueError("Only rejected fill events may include reject details.")
        if self.status in {OrderStatus.ACCEPTED, OrderStatus.CANCELED}:
            if self.filled_size != 0 or self.average_price is not None:
                raise ValueError(
                    "accepted and canceled fills cannot contain execution values"
                )
            return
        if self.filled_size <= 0 or self.average_price is None:
            raise ValueError("filled and partial fills require execution values")
        if self.status is OrderStatus.FILLED and self.filled_size != self.requested_size:
            raise ValueError("filled size must equal requested size")
        if self.status is OrderStatus.PARTIAL and self.filled_size >= self.requested_size:
            raise ValueError("partial fill size must be below requested size")

    @property
    def has_execution(self) -> bool:
        return self.status in {OrderStatus.FILLED, OrderStatus.PARTIAL}

    @property
    def execution_price(self) -> Decimal:
        if self.average_price is None:
            raise ValueError("fill has no execution price")
        return self.average_price

    def _validate_identity(self) -> None:
        for name, value in (("order ID", self.order_id), ("token ID", self.token_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"fill {name} must be non-empty text")

    def _validate_order_id(self) -> None:
        if not isinstance(self.order_id, str) or not self.order_id.strip():
            raise ValueError("fill order ID must be non-empty text")

    def _validate_nonnegative_execution_amounts(self) -> None:
        for name, value in (
            ("filled size", self.filled_size),
            ("fee", self.fee_usdc),
        ):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"fill {name} must be a finite nonnegative Decimal")

    def _validate_amounts(self) -> None:
        if (
            not isinstance(self.requested_size, Decimal)
            or not self.requested_size.is_finite()
        ):
            raise ValueError("fill requested size must be a finite Decimal")
        self._validate_nonnegative_execution_amounts()
        if self.requested_size <= 0:
            raise ValueError("fill requested size must be positive")
        if self.filled_size > self.requested_size:
            raise ValueError("fill size cannot exceed requested size")
        if self.average_price is not None:
            if not is_outcome_price(self.average_price):
                raise ValueError(
                    "fill average price must be a finite Decimal between 0 and 1"
                )

    @classmethod
    def rejected(
        cls,
        *,
        order_id: str,
        token_id: str,
        side: Side,
        requested_size: Decimal,
        received_at_ms: int,
        reject_reason: FillRejectReason,
        reject_message: str,
    ) -> FillEvent:
        return cls(
            order_id=order_id,
            token_id=token_id,
            side=side,
            status=OrderStatus.REJECTED,
            requested_size=requested_size,
            filled_size=Decimal("0"),
            average_price=None,
            fee_usdc=Decimal("0"),
            received_at_ms=received_at_ms,
            reject_reason=reject_reason,
            reject_message=reject_message,
        )
