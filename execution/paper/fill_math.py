from __future__ import annotations

from decimal import Decimal

from bots.execution.orders import taker_fee_usdc
from bots.execution.paper.book import consume_levels, slippage_limit_price
from bots.framework.events import FillEvent, OrderRequest, OrderStatus
from bots.framework.events.books import BookSnapshot

EMPTY_FILL_VALUE = Decimal("0")


def simulate_fill(
    *,
    order: OrderRequest,
    book: BookSnapshot,
    fee_rate: Decimal,
    max_slippage_pct: Decimal,
    order_id: str,
    fill_time_ms: int,
) -> FillEvent | None:
    slippage_cap = slippage_limit_price(
        side=order.side,
        reference_price=order.price,
        max_slippage_pct=max_slippage_pct,
    )
    consumed = consume_levels(
        order.side,
        book.executable_levels(order.side),
        requested_size=order.size,
        slippage_limit_price=slippage_cap,
    )
    if not consumed:
        return None
    filled_size = sum((level.size for level in consumed), EMPTY_FILL_VALUE)
    filled_notional = sum(
        (level.notional_usdc for level in consumed),
        EMPTY_FILL_VALUE,
    )
    average_price = filled_notional / filled_size
    fee_usdc = sum(
        (
            taker_fee_usdc(level.size, fee_rate, level.price)
            for level in consumed
        ),
        EMPTY_FILL_VALUE,
    )
    status = OrderStatus.FILLED if filled_size == order.size else OrderStatus.PARTIAL
    return FillEvent(
        order_id=order_id,
        token_id=order.token_id,
        side=order.side,
        status=status,
        requested_size=order.size,
        filled_size=filled_size,
        average_price=average_price,
        fee_usdc=fee_usdc,
        received_at_ms=fill_time_ms,
    )
