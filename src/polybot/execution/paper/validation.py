from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.framework.events import FillRejectReason, OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.prices import (
    is_decimal_in_unit_interval,
    is_outcome_price,
)

ORDER_SIZE_FLOOR = Decimal("0")


def validate_order(order: OrderRequest) -> tuple[FillRejectReason, str] | None:
    if not order.token_id:
        return FillRejectReason.MISSING_TOKEN_ID, "order is missing token_id"
    if not isinstance(order.side, Side):
        return FillRejectReason.BAD_SIDE, "order side is invalid"
    if order.source_id is not None and (
        not isinstance(order.source_id, str)
        or not order.source_id
        or "\n" in order.source_id
        or "\r" in order.source_id
    ):
        return (
            FillRejectReason.INVALID_SOURCE_ID,
            "order source_id must be non-empty single-line text",
        )
    try:
        if not is_outcome_price(order.price):
            return (
                FillRejectReason.BAD_PRICE,
                "order price must be finite and between 0 and 1",
            )
        if not order.size.is_finite() or order.size <= ORDER_SIZE_FLOOR:
            return FillRejectReason.BAD_SIZE, "order size must be finite and positive"
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return FillRejectReason.BAD_PRICE, "order price and size must be decimals"
    return None


def classify_book(
    order: OrderRequest,
    book: BookSnapshot,
    fill_time_ms: int,
    max_age_ms: int,
) -> FillRejectReason | None:
    if book.token_id != order.token_id:
        return FillRejectReason.BOOK_MISMATCH
    if order.market_slug is not None or order.condition_id is not None:
        if book.market_slug is None or book.condition_id is None:
            return FillRejectReason.BOOK_MISMATCH
    if order.market_slug is not None and book.market_slug != order.market_slug:
        return FillRejectReason.BOOK_MISMATCH
    if order.condition_id is not None and book.condition_id != order.condition_id:
        return FillRejectReason.BOOK_MISMATCH
    issue = book.validation_issue(fill_time_ms, max_age_ms)
    return None if issue is None else FillRejectReason(issue.value)


def valid_fee_rate(value: object) -> Decimal | None:
    return value if is_decimal_in_unit_interval(value, include_zero=True) else None
