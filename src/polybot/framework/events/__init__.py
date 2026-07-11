from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from polybot.framework.events.book_validation import BookValidationIssue


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


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
    NO_DEPTH_WITHIN_SLIPPAGE = "no_depth_within_slippage"
    DUPLICATE_SOURCE_ID = "duplicate_source_id"


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
        if self.status is OrderStatus.REJECTED:
            if self.reject_reason is None:
                raise ValueError("Rejected fill events require a reject_reason.")
            if self.reject_message is None or not self.reject_message.strip():
                raise ValueError("Rejected fill events require a reject_message.")
            return
        if self.reject_reason is not None or self.reject_message is not None:
            raise ValueError("Only rejected fill events may include reject details.")

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
