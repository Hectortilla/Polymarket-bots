from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.framework.events import FillRejectReason, OrderRequest, Side
from polybot.framework.events.books import BOOK_PRICE_CEILING, BookSnapshot, PRICE_FLOOR

ORDER_VALUE_FLOOR = PRICE_FLOOR


def validate_order(order: OrderRequest) -> tuple[FillRejectReason, str] | None:
    if not order.token_id:
        return FillRejectReason.MISSING_TOKEN_ID, "order is missing token_id"
    if not isinstance(order.side, Side):
        return FillRejectReason.BAD_SIDE, "order side is invalid"
    try:
        if not order.price.is_finite() or not ORDER_VALUE_FLOOR < order.price <= BOOK_PRICE_CEILING:
            return FillRejectReason.BAD_PRICE, "order price must be finite and between 0 and 1"
        if not order.size.is_finite() or order.size <= ORDER_VALUE_FLOOR:
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
    if not isinstance(value, Decimal):
        return None
    try:
        if value.is_finite() and ORDER_VALUE_FLOOR <= value <= BOOK_PRICE_CEILING:
            return value
    except (InvalidOperation, TypeError, ValueError):
        pass
    return None
