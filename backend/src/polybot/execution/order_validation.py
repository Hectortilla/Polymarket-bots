"""Order-shape policy shared by execution and decision previews."""

from decimal import Decimal, InvalidOperation

from polybot.framework.events import FillRejectReason, OrderRequest, Side
from polybot.framework.events.prices import is_outcome_price

ORDER_SIZE_FLOOR = Decimal("0")


def validate_order(order: OrderRequest) -> tuple[FillRejectReason, str] | None:
    if not isinstance(order.token_id, str) or not order.token_id.strip():
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
