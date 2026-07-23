"""Static full-run terminal charts for saved performance results."""

from __future__ import annotations

import argparse
import csv
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite, nan
from pathlib import Path

import asciichartpy
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polybot.cli.charting import (
    DIMMED_VALUE_COLOR,
    chart_time_range,
    padded_value_bounds,
    render_chart,
    resample_indices,
    split_stale_samples,
)
from polybot.performance.contracts import (
    EQUITY_FIELDS,
    EQUITY_FILE_NAME,
    SUMMARY_FILE_NAME,
    PerformanceSummaryV1,
)
from polybot.performance.valuation import ValuationStatus


MIN_CHART_DISPLAY_POINTS = 12
MAX_CHART_DISPLAY_POINTS = 120
CHART_HORIZONTAL_OVERHEAD = 16
PNL_CHART_HEIGHT = 5


class PerformanceChartError(ValueError):
    """A saved performance run cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class PerformanceChartData:
    results_dir: Path
    summary: PerformanceSummaryV1
    timestamps_ms: Sequence[int]
    pnl_values: Sequence[float]
    stale_samples: Sequence[bool]


def load_performance_chart_data(results_dir: str | Path) -> PerformanceChartData:
    directory = Path(results_dir)
    if not directory.is_dir():
        raise PerformanceChartError(
            f"performance results directory does not exist: {directory}"
        )
    summary = _read_summary(directory / SUMMARY_FILE_NAME)
    if summary.artifacts.get("equity") != EQUITY_FILE_NAME:
        raise PerformanceChartError(
            f"performance summary does not reference {EQUITY_FILE_NAME}"
        )
    timestamps_ms, pnl_values, stale_samples = _read_equity(
        directory / EQUITY_FILE_NAME
    )
    return PerformanceChartData(
        results_dir=directory,
        summary=summary,
        timestamps_ms=timestamps_ms,
        pnl_values=pnl_values,
        stale_samples=stale_samples,
    )


def render_performance_chart(data: PerformanceChartData, width: int) -> Panel:
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


def print_performance_chart(
    results_dir: str | Path,
    *,
    console: Console | None = None,
) -> None:
    output = console or Console()
    data = load_performance_chart_data(results_dir)
    try:
        output.print(render_performance_chart(data, output.size.width))
    except Exception as error:
        raise PerformanceChartError(
            f"could not render performance chart: {error}"
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Display the full-run net-PnL chart from saved results"
    )
    parser.add_argument("results_dir", type=Path, metavar="RESULTS_DIR")
    args = parser.parse_args(argv)
    try:
        print_performance_chart(args.results_dir)
    except PerformanceChartError as error:
        parser.error(str(error))
    return 0


def _read_summary(path: Path) -> PerformanceSummaryV1:
    try:
        return PerformanceSummaryV1.read(path)
    except (OSError, UnicodeError, ValueError) as error:
        raise PerformanceChartError(
            f"could not read performance summary {path}: {error}"
        ) from error


def _read_equity(
    path: Path,
) -> tuple[Sequence[int], Sequence[float], Sequence[bool]]:
    try:
        with path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != EQUITY_FIELDS:
                raise PerformanceChartError(
                    f"performance equity header does not match schema: {path}"
                )
            timestamps = array("q")
            values = array("d")
            stale_samples = bytearray()
            last_value: float | None = None
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise PerformanceChartError(
                        f"performance equity row {line_number} is incomplete"
                    )
                timestamp = _timestamp(row["timestamp_ms"], line_number)
                if timestamps and timestamp < timestamps[-1]:
                    raise PerformanceChartError(
                        f"performance equity timestamp moves backward at row {line_number}"
                    )
                status = _valuation_status(row["valuation_status"], line_number)
                value = _pnl_value(row["pnl_usdc"], status, line_number)
                if value is None:
                    values.append(nan if last_value is None else last_value)
                    stale_samples.append(last_value is not None)
                else:
                    last_value = value
                    values.append(value)
                    stale_samples.append(status is not ValuationStatus.FRESH)
                timestamps.append(timestamp)
    except PerformanceChartError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise PerformanceChartError(
            f"could not read performance equity {path}: {error}"
        ) from error
    if not timestamps:
        raise PerformanceChartError(f"performance equity has no samples: {path}")
    return timestamps, values, stale_samples


def _timestamp(value: str, line_number: int) -> int:
    try:
        timestamp = int(value)
    except ValueError as error:
        raise PerformanceChartError(
            f"performance equity timestamp is invalid at row {line_number}"
        ) from error
    if timestamp < 0:
        raise PerformanceChartError(
            f"performance equity timestamp is negative at row {line_number}"
        )
    return timestamp


def _valuation_status(value: str, line_number: int) -> ValuationStatus:
    try:
        return ValuationStatus(value)
    except ValueError as error:
        raise PerformanceChartError(
            f"performance equity valuation status is invalid at row {line_number}"
        ) from error


def _pnl_value(
    value: str,
    status: ValuationStatus,
    line_number: int,
) -> float | None:
    if not value:
        if status is not ValuationStatus.UNAVAILABLE:
            raise PerformanceChartError(
                f"performance equity PnL is missing at row {line_number}"
            )
        return None
    if status is ValuationStatus.UNAVAILABLE:
        raise PerformanceChartError(
            f"performance equity unavailable PnL must be empty at row {line_number}"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise PerformanceChartError(
            f"performance equity PnL is invalid at row {line_number}"
        ) from error
    if not parsed.is_finite():
        raise PerformanceChartError(
            f"performance equity PnL is not finite at row {line_number}"
        )
    result = float(parsed)
    if not isfinite(result):
        raise PerformanceChartError(
            f"performance equity PnL is outside chart range at row {line_number}"
        )
    return result


def _chart_display_points(width: int) -> int:
    return max(
        MIN_CHART_DISPLAY_POINTS,
        min(MAX_CHART_DISPLAY_POINTS, width - CHART_HORIZONTAL_OVERHEAD),
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
        if status == ValuationStatus.FRESH.value
        else "yellow" if status == ValuationStatus.STALE.value else "red"
    )
    return _metric("Valuation", status, style)


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
    kind = summary.provenance.get("kind")
    if kind == "backtest":
        return "Backtest"
    if kind == "paper":
        return "Paper run"
    return "Performance run"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
