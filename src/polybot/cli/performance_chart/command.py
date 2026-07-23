"""Command entrypoint for displaying a saved full-run performance chart."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from .artifacts import load_performance_chart_data
from .contracts import PerformanceChartError
from .rendering import render_performance_chart


def print_performance_chart(
    results_dir: str | Path,
    *,
    console: Console | None = None,
) -> None:
    """Load and display one finalized performance run."""

    output = console or Console()
    data = load_performance_chart_data(results_dir)
    try:
        output.print(render_performance_chart(data, output.size.width))
    except Exception as error:
        raise PerformanceChartError(
            f"could not render performance chart: {error}"
        ) from error


def main(argv: list[str] | None = None) -> int:
    """Run the standalone saved-performance chart command."""

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
