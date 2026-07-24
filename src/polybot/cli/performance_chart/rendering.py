"""Rich terminal rendering for validated saved-performance chart data."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import asciichartpy
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polybot.cli.charting import (
    DIMMED_VALUE_COLOR,
    MAX_TERMINAL_CHART_POINTS,
    MIN_TERMINAL_CHART_POINTS,
    chart_time_range,
    padded_value_bounds,
    render_chart,
    resample_indices,
    split_stale_samples,
)
from polybot.performance.contracts.run import PerformanceRunKind
from polybot.performance.contracts.summary import PerformanceSummaryV1
from polybot.performance.contracts.valuation_status import ValuationStatus

from .contracts import PerformanceChartData, PerformanceChartError


CHART_HORIZONTAL_OVERHEAD = 16
PNL_CHART_HEIGHT = 5


def render_performance_chart(data: PerformanceChartData, width: int) -> Panel:
    """Render a complete, validated PnL history at the current terminal width."""

    display_points = _chart_display_points(width)
    indices = resample_indices(len(data.pnl_values), display_points)
    values = [data.pnl_values[index] for index in indices]
    stale_samples = [data.stale_samples[index] for index in indices]
    minimum, maximum = padded_value_bounds(values)
    chart = render_chart(
        split_stale_samples(values, stale_samples),
        (asciichartpy.lightgreen, DIMMED_VALUE_COLOR),
        PNL_CHART_HEIGHT,
        "PnL unavailable",
        minimum=minimum,
        maximum=maximum,
    )
    visible_range = (
        data.timestamps_ms[0] / 1_000,
        data.timestamps_ms[-1] / 1_000,
    )
    title = f"{_run_kind_label(data.summary)} net PnL · {data.summary.status.value}"
    if data.summary.partial:
        title += " (partial)"
    return Panel(
        Group(
            _performance_summary(data.summary),
            Text("Net PnL (USDC)", style="bold green"),
            Text(
                "green: current · dim green: stale or unavailable",
                style="bright_green",
            ),
            chart,
            chart_time_range(visible_range, display_points),
        ),
        title=title,
        border_style="cyan",
    )


def _chart_display_points(width: int) -> int:
    return max(
        MIN_TERMINAL_CHART_POINTS,
        min(MAX_TERMINAL_CHART_POINTS, width - CHART_HORIZONTAL_OVERHEAD),
    )


def _performance_summary(summary: PerformanceSummaryV1) -> Table:
    metrics = summary.metrics
    table = Table.grid(expand=True, padding=(0, 1))
    for _ in range(4):
        table.add_column(ratio=1)
    table.add_row(
        _count_metric("Fills", metrics.fill_count, "bold green"),
        _count_metric("Orders", metrics.order_count, "white"),
        _count_metric("Rejected", metrics.rejected_order_count, "yellow"),
        _count_metric("Resolved", metrics.resolution_count, "cyan"),
    )
    table.add_row(
        _decimal_metric("Net PnL", metrics.net_pnl_usdc, signed=True),
        _percent_metric("Return", metrics.return_fraction),
        _decimal_metric("Drawdown", metrics.max_drawdown_usdc),
        _decimal_metric("Fees", metrics.fees_usdc),
    )
    table.add_row(
        _decimal_metric("Start", metrics.initial_equity_usdc),
        _decimal_metric("End", metrics.final_equity_usdc),
        _decimal_metric("Notional", metrics.filled_notional_usdc),
        _valuation_metric(summary),
    )
    return table


def _count_metric(label: str, value: int, style: str) -> Text:
    return _metric(label, f"{value:,}", style)


def _decimal_metric(
    label: str,
    value: str | None,
    *,
    signed: bool = False,
) -> Text:
    if value is None:
        return _metric(label, "N/A", "dim")
    parsed = _summary_decimal(value, label)
    if signed:
        sign = "+" if parsed > 0 else "-" if parsed < 0 else ""
        formatted = f"{sign}${abs(parsed):,.2f}"
        style = "bold green" if parsed > 0 else "bold red" if parsed < 0 else "white"
    else:
        formatted = f"${parsed:,.2f}"
        style = "white"
    return _metric(label, formatted, style)


def _percent_metric(label: str, value: str | None) -> Text:
    if value is None:
        return _metric(label, "N/A", "dim")
    percentage = _summary_decimal(value, label) * 100
    sign = "+" if percentage > 0 else ""
    style = (
        "bold green"
        if percentage > 0
        else "bold red" if percentage < 0 else "white"
    )
    return _metric(label, f"{sign}{percentage:.2f}%", style)


def _valuation_metric(summary: PerformanceSummaryV1) -> Text:
    status = summary.valuation.final_status
    style = (
        "green"
        if status is ValuationStatus.FRESH
        else "yellow" if status is ValuationStatus.STALE else "red"
    )
    return _metric("Valuation", status.value, style)


def _metric(label: str, value: str, style: str) -> Text:
    result = Text()
    result.append(f"{label} ", style="dim")
    result.append(value, style=style)
    return result


def _summary_decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise PerformanceChartError(
            f"performance summary {label} is invalid"
        ) from error
    if not parsed.is_finite():
        raise PerformanceChartError(
            f"performance summary {label} is not finite"
        )
    return parsed


def _run_kind_label(summary: PerformanceSummaryV1) -> str:
    if summary.provenance.kind is PerformanceRunKind.BACKTEST:
        return "Backtest"
    if summary.provenance.kind is PerformanceRunKind.PAPER:
        return "Paper run"
    return "Performance run"
