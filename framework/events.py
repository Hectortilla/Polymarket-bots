from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

ZERO_DECIMAL = Decimal("0")
BOOK_PRICE_CEILING = Decimal("1")


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
    BOOK_STALE = "book_stale"
    BAD_BOOK_LEVEL = "bad_book_level"
    MARKET_UNAVAILABLE = "market_unavailable"
    MARKET_FEE_INVALID = "market_fee_invalid"
    NO_DEPTH_WITHIN_SLIPPAGE = "no_depth_within_slippage"


class WalletTradeKind(StrEnum):
    TRADE = "trade"
    BACKFILL = "backfill"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    size: Decimal

    def is_valid(self) -> bool:
        try:
            return (
                self.price.is_finite()
                and self.size.is_finite()
                and ZERO_DECIMAL < self.price <= BOOK_PRICE_CEILING
                and self.size > ZERO_DECIMAL
            )
        except (AttributeError, InvalidOperation, TypeError, ValueError):
            return False


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    token_id: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    received_at_ms: int
    market_slug: str | None = None
    condition_id: str | None = None

    def is_fresh(self, now_ms: int, max_age_ms: int) -> bool:
        age_ms = max(0, now_ms - self.received_at_ms)
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

    def executable_levels(self, side: Side) -> tuple[BookLevel, ...]:
        if side is Side.BUY:
            return tuple(sorted(self.asks, key=lambda level: level.price))
        return tuple(sorted(self.bids, key=lambda level: level.price, reverse=True))


@dataclass(frozen=True, slots=True)
class WalletTradeEvent:
    wallet: str
    condition_id: str
    token_id: str
    side: Side
    size: Decimal
    price: Decimal
    source_id: str
    trade_timestamp_ms: int
    observed_at_ms: int
    kind: WalletTradeKind = WalletTradeKind.TRADE
    market_slug: str | None = None
    transaction_hash: str | None = None
    outcome: str | None = None


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
        fee_usdc: Decimal,
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
            fee_usdc=fee_usdc,
            received_at_ms=received_at_ms,
            reject_reason=reject_reason,
            reject_message=reject_message,
        )
