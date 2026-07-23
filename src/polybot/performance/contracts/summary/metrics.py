"""Metrics section of a persisted performance summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..files import PerformanceMetricsField
from ..parsing import (
    nonnegative_int,
    optional_decimal_text,
    optional_nonnegative_int,
    required_decimal_text,
    require_exact_keys,
)


@dataclass(frozen=True, slots=True)
class PerformanceMetricsSummary:
    """Validated aggregate execution and equity metrics for one run."""

    initial_cash_usdc: str
    initial_equity_usdc: str | None
    final_cash_usdc: str
    final_marked_position_value_usdc: str | None
    final_equity_usdc: str | None
    gross_pnl_usdc: str | None
    net_pnl_usdc: str | None
    return_fraction: str | None
    fees_usdc: str
    filled_notional_usdc: str
    max_drawdown_usdc: str | None
    max_drawdown_fraction: str | None
    order_count: int
    fill_count: int
    rejected_order_count: int
    coverage_gap_rejected_order_count: int
    resolution_count: int
    event_count: int
    dispatch_count: int
    accepted_dispatch_count: int
    skipped_dispatch_count: int

    def __post_init__(self) -> None:
        if (
            self.accepted_dispatch_count + self.skipped_dispatch_count
            > self.dispatch_count
        ):
            raise ValueError(
                "performance summary dispatch outcomes exceed dispatch count"
            )
        if self.fill_count > self.order_count:
            raise ValueError("performance summary fills exceed order count")
        if self.rejected_order_count > self.order_count:
            raise ValueError("performance summary rejected orders exceed order count")
        if self.coverage_gap_rejected_order_count > self.rejected_order_count:
            raise ValueError(
                "performance summary coverage-gap rejections exceed rejected orders"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PerformanceMetricsSummary:
        """Decode the exact metrics object and enforce its aggregate invariants."""
        require_exact_keys(payload, PerformanceMetricsField, "metrics")
        return cls(
            initial_cash_usdc=required_decimal_text(
                payload, PerformanceMetricsField.INITIAL_CASH_USDC
            ),
            initial_equity_usdc=optional_decimal_text(
                payload, PerformanceMetricsField.INITIAL_EQUITY_USDC
            ),
            final_cash_usdc=required_decimal_text(
                payload, PerformanceMetricsField.FINAL_CASH_USDC
            ),
            final_marked_position_value_usdc=optional_decimal_text(
                payload, PerformanceMetricsField.FINAL_MARKED_POSITION_VALUE_USDC
            ),
            final_equity_usdc=optional_decimal_text(
                payload, PerformanceMetricsField.FINAL_EQUITY_USDC
            ),
            gross_pnl_usdc=optional_decimal_text(
                payload, PerformanceMetricsField.GROSS_PNL_USDC
            ),
            net_pnl_usdc=optional_decimal_text(
                payload, PerformanceMetricsField.NET_PNL_USDC
            ),
            return_fraction=optional_decimal_text(
                payload, PerformanceMetricsField.RETURN_FRACTION
            ),
            fees_usdc=required_decimal_text(
                payload, PerformanceMetricsField.FEES_USDC
            ),
            filled_notional_usdc=required_decimal_text(
                payload, PerformanceMetricsField.FILLED_NOTIONAL_USDC
            ),
            max_drawdown_usdc=optional_decimal_text(
                payload, PerformanceMetricsField.MAX_DRAWDOWN_USDC
            ),
            max_drawdown_fraction=optional_decimal_text(
                payload, PerformanceMetricsField.MAX_DRAWDOWN_FRACTION
            ),
            order_count=nonnegative_int(payload, PerformanceMetricsField.ORDER_COUNT),
            fill_count=nonnegative_int(payload, PerformanceMetricsField.FILL_COUNT),
            rejected_order_count=nonnegative_int(
                payload, PerformanceMetricsField.REJECTED_ORDER_COUNT
            ),
            coverage_gap_rejected_order_count=optional_nonnegative_int(
                payload,
                PerformanceMetricsField.COVERAGE_GAP_REJECTED_ORDER_COUNT,
            ),
            resolution_count=nonnegative_int(
                payload, PerformanceMetricsField.RESOLUTION_COUNT
            ),
            event_count=nonnegative_int(payload, PerformanceMetricsField.EVENT_COUNT),
            dispatch_count=nonnegative_int(
                payload, PerformanceMetricsField.DISPATCH_COUNT
            ),
            accepted_dispatch_count=nonnegative_int(
                payload, PerformanceMetricsField.ACCEPTED_DISPATCH_COUNT
            ),
            skipped_dispatch_count=nonnegative_int(
                payload, PerformanceMetricsField.SKIPPED_DISPATCH_COUNT
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Encode the stable metrics section."""
        return {
            PerformanceMetricsField.INITIAL_CASH_USDC: self.initial_cash_usdc,
            PerformanceMetricsField.INITIAL_EQUITY_USDC: self.initial_equity_usdc,
            PerformanceMetricsField.FINAL_CASH_USDC: self.final_cash_usdc,
            PerformanceMetricsField.FINAL_MARKED_POSITION_VALUE_USDC: (
                self.final_marked_position_value_usdc
            ),
            PerformanceMetricsField.FINAL_EQUITY_USDC: self.final_equity_usdc,
            PerformanceMetricsField.GROSS_PNL_USDC: self.gross_pnl_usdc,
            PerformanceMetricsField.NET_PNL_USDC: self.net_pnl_usdc,
            PerformanceMetricsField.RETURN_FRACTION: self.return_fraction,
            PerformanceMetricsField.FEES_USDC: self.fees_usdc,
            PerformanceMetricsField.FILLED_NOTIONAL_USDC: self.filled_notional_usdc,
            PerformanceMetricsField.MAX_DRAWDOWN_USDC: self.max_drawdown_usdc,
            PerformanceMetricsField.MAX_DRAWDOWN_FRACTION: self.max_drawdown_fraction,
            PerformanceMetricsField.ORDER_COUNT: self.order_count,
            PerformanceMetricsField.FILL_COUNT: self.fill_count,
            PerformanceMetricsField.REJECTED_ORDER_COUNT: self.rejected_order_count,
            PerformanceMetricsField.COVERAGE_GAP_REJECTED_ORDER_COUNT: (
                self.coverage_gap_rejected_order_count
            ),
            PerformanceMetricsField.RESOLUTION_COUNT: self.resolution_count,
            PerformanceMetricsField.EVENT_COUNT: self.event_count,
            PerformanceMetricsField.DISPATCH_COUNT: self.dispatch_count,
            PerformanceMetricsField.ACCEPTED_DISPATCH_COUNT: (
                self.accepted_dispatch_count
            ),
            PerformanceMetricsField.SKIPPED_DISPATCH_COUNT: (
                self.skipped_dispatch_count
            ),
        }
