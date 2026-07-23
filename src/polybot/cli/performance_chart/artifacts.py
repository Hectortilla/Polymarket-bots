"""Validation and projection of saved performance artifacts for charting."""

from __future__ import annotations

import csv
from array import array
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from math import isfinite, nan
from pathlib import Path

from polybot.performance.contracts.files import (
    EQUITY_FIELDS,
    EQUITY_FILE_NAME,
    EquityField,
    SUMMARY_FILE_NAME,
)
from polybot.performance.contracts.summary import PerformanceSummaryV1
from polybot.performance.valuation import ValuationStatus

from .contracts import PerformanceChartData, PerformanceChartError


MAX_CHART_TIMESTAMP_MS = (1 << 63) - 1


def load_performance_chart_data(results_dir: str | Path) -> PerformanceChartData:
    """Read the exact saved-artifact contract needed by the chart renderer."""

    directory = Path(results_dir)
    if not directory.is_dir():
        raise PerformanceChartError(
            f"performance results directory does not exist: {directory}"
        )
    summary = _read_summary(directory / SUMMARY_FILE_NAME)
    if summary.artifacts.equity != EQUITY_FILE_NAME:
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
                timestamp = _timestamp(row[EquityField.TIMESTAMP_MS], line_number)
                if timestamps and timestamp < timestamps[-1]:
                    raise PerformanceChartError(
                        "performance equity timestamp moves backward at row "
                        f"{line_number}"
                    )
                status = _valuation_status(
                    row[EquityField.VALUATION_STATUS],
                    line_number,
                )
                value = _pnl_value(row[EquityField.PNL_USDC], status, line_number)
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
    if timestamp > MAX_CHART_TIMESTAMP_MS:
        raise PerformanceChartError(
            f"performance equity timestamp is outside chart range at row {line_number}"
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
