"""Order result rows, execution deduplication, and order performance counters."""

from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
)
from polybot.performance.contracts.files import OrderField

from .csv_output import PerformanceCsvOutput
from .serialization import ZERO_USDC_AMOUNT, decimal_text, optional_decimal_text


class PerformanceOrderRecorder:
    def __init__(self, output: PerformanceCsvOutput) -> None:
        self._output = output
        self.order_count = 0
        self.fill_count = 0
        self._recorded_fill_order_ids: set[str] = set()
        self.rejected_count = 0
        self.coverage_gap_rejected_order_count = 0
        self.filled_notional_usdc = ZERO_USDC_AMOUNT

    def record(
        self, *, submitted_at_ms: int, order: OrderRequest, fill: FillEvent
    ) -> bool:
        self._output.write_order(
            {
                OrderField.SUBMITTED_AT_MS: submitted_at_ms,
                OrderField.COMPLETED_AT_MS: fill.received_at_ms,
                OrderField.ORDER_ID: fill.order_id,
                OrderField.MARKET_SLUG: order.market_slug,
                OrderField.CONDITION_ID: order.condition_id,
                OrderField.TOKEN_ID: order.token_id,
                OrderField.SIDE: order.side.value,
                OrderField.REQUESTED_PRICE: decimal_text(order.price),
                OrderField.REQUESTED_SIZE: decimal_text(order.size),
                OrderField.STATUS: fill.status.value,
                OrderField.FILLED_SIZE: decimal_text(fill.filled_size),
                OrderField.AVERAGE_PRICE: optional_decimal_text(fill.average_price),
                OrderField.FEE_USDC: decimal_text(fill.fee_usdc),
                OrderField.REJECT_REASON: (
                    None if fill.reject_reason is None else fill.reject_reason.value
                ),
                OrderField.REJECT_MESSAGE: fill.reject_message,
                OrderField.STRATEGY_REASON: order.reason,
                OrderField.SOURCE_ID: order.source_id,
            }
        )
        self.order_count += 1
        if fill.status is OrderStatus.REJECTED:
            self.rejected_count += 1
        if fill.reject_reason is FillRejectReason.BACKTEST_COVERAGE_GAP:
            self.coverage_gap_rejected_order_count += 1
        is_new_fill = (
            fill.has_execution and fill.order_id not in self._recorded_fill_order_ids
        )
        if is_new_fill:
            self._recorded_fill_order_ids.add(fill.order_id)
            self.fill_count += 1
            self.filled_notional_usdc += fill.filled_size * fill.execution_price
        return is_new_fill
