"""Backtest-specific command construction, execution, and reporting."""

from __future__ import annotations

import sys

from polybot.backtesting.contracts import (
    BacktestGapPolicy,
    BacktestOptions,
    BacktestResult,
)
from polybot.backtesting.service.runner import run_backtest
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.performance.contracts.files import SUMMARY_FILE_NAME
from polybot.performance.contracts.summary import PerformanceSummaryV1

from .performance_chart.command import print_performance_chart
from .performance_chart.contracts import PerformanceChartError


PARTIAL_RECORDING_WARNING = "Backtest source is a partial recording session"
BLACKOUT_GAP_WARNING = "Backtest used blackout coverage-gap handling"
BACKTEST_CHART_WARNING = (
    "Backtest completed, but the PnL chart could not be rendered"
)

async def execute_backtest(
    bot: BaseBot,
    config: BotConfig,
    *,
    bot_spec: str,
    options: BacktestOptions,
) -> None:
    result = await run_backtest(
        bot,
        config,
        bot_spec=bot_spec,
        options=options,
    )
    print_backtest_summary(result)
    try:
        print_performance_chart(result.results_dir)
    except PerformanceChartError as error:
        print(f"{BACKTEST_CHART_WARNING}: {error}", file=sys.stderr)


def print_backtest_summary(result: BacktestResult) -> None:
    summary_path = result.results_dir / SUMMARY_FILE_NAME
    summary = PerformanceSummaryV1.read(summary_path)
    metrics = summary.metrics
    valuation = summary.valuation
    if result.selection.uses_partial_session:
        print(
            f"{PARTIAL_RECORDING_WARNING}: "
            f"{result.selection.session_integrity_status.value}; "
            f"committed through {result.selection.end_at_ms}"
        )
    if result.selection.gap_policy is BacktestGapPolicy.BLACKOUT:
        print(
            f"{BLACKOUT_GAP_WARNING}: "
            f"gaps={len(result.selection.coverage_gap_ids)} "
            f"duration={result.selection.coverage_gap_duration_ms}ms "
            f"open={result.selection.coverage_gap_open_count}; "
            "results are approximate"
        )
    print(
        "Backtest completed: "
        f"events={metrics.event_count} "
        f"orders={metrics.order_count} fills={metrics.fill_count}"
    )
    print(
        f"Net PnL: {metrics.net_pnl_usdc} USDC; "
        f"return: {metrics.return_fraction}; "
        f"max drawdown: {metrics.max_drawdown_usdc} USDC"
    )
    print(
        f"Valuation: {valuation.final_status} "
        f"(complete={str(valuation.complete).lower()})"
    )
    print(f"Results: {result.results_dir}")
