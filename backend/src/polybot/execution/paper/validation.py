from __future__ import annotations

from decimal import Decimal

from polybot.framework.events import FillRejectReason, OrderRequest
from polybot.framework.events.book_validation import BookValidationIssue
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.prices import (
    is_decimal_in_unit_interval,
)

BOOK_VALIDATION_REJECT_REASON = {
    BookValidationIssue.MISSING_MARKET_IDENTITY: FillRejectReason.BOOK_MISMATCH,
    BookValidationIssue.IDENTITY_MISMATCH: FillRejectReason.BOOK_MISMATCH,
    BookValidationIssue.BAD_TIMESTAMP: FillRejectReason.BAD_BOOK_TIMESTAMP,
    BookValidationIssue.FUTURE_DATED: FillRejectReason.BOOK_FUTURE_DATED,
    BookValidationIssue.STALE: FillRejectReason.BOOK_STALE,
    BookValidationIssue.BAD_LEVEL: FillRejectReason.BAD_BOOK_LEVEL,
    BookValidationIssue.CROSSED: FillRejectReason.BOOK_CROSSED,
}


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
    return None if issue is None else BOOK_VALIDATION_REJECT_REASON[issue]


def valid_fee_rate(value: object) -> Decimal | None:
    return value if is_decimal_in_unit_interval(value, include_zero=True) else None
