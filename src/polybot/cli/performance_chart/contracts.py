"""Typed inputs and errors for saved-performance charting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from polybot.performance.contracts.summary import PerformanceSummaryV1


class PerformanceChartError(ValueError):
    """A saved performance run cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class PerformanceChartData:
    """Validated full-run values required by the terminal chart renderer."""

    results_dir: Path
    summary: PerformanceSummaryV1
    timestamps_ms: Sequence[int]
    pnl_values: Sequence[float]
    stale_samples: Sequence[bool]
