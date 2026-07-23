"""Command-line argument parsing and bot startup."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestGapPolicy,
    BacktestOptions,
    BacktestResult,
)
from polybot.backtesting.service import run_backtest
from polybot.framework.config.models import BotConfig, BotMode
from polybot.performance.artifacts.errors import PerformanceArtifactError
from polybot.performance.contracts.files import (
    DEFAULT_REPORT_INTERVAL_MS,
    SUMMARY_FILE_NAME,
)
from polybot.performance.contracts.summary import (
    PerformanceSummaryV1,
)

from .config import DEFAULT_DOTENV_PATH, load_dotenv, parse_overrides
from .dashboard.controller import TerminalDashboard
from .factories import load_bot
from .performance_chart.command import print_performance_chart
from .performance_chart.contracts import PerformanceChartError
from polybot.runtime import run_bot

INTERACTIVE_TERMINAL_REQUIRED_MESSAGE = (
    "dashboard requires an interactive terminal; use --no-dashboard for headless runs"
)
TERM_ENV_KEY = "TERM"
NON_INTERACTIVE_TERMINAL = "dumb"
BACKTEST_DASHBOARD_MESSAGE = "backtests are headless; omit --dashboard"
PARTIAL_RECORDING_WARNING = "Backtest source is a partial recording session"
BLACKOUT_GAP_WARNING = "Backtest used blackout coverage-gap handling"
BACKTEST_CHART_WARNING = "Backtest completed, but the PnL chart could not be rendered"


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    load_dotenv(args.dotenv)
    overrides = parse_overrides(args.override)
    config = BotConfig.from_env(args.bot.rsplit(":", 1)[-1]).with_overrides(**overrides)
    if args.backtest is not None and config.mode is BotMode.LIVE:
        parser.error("backtesting cannot run with BOT_MODE=live")
    if args.backtest is None and any(
        value is not None
        for value in (args.session, args.start_ms, args.end_ms)
    ):
        parser.error("--session, --start-ms, and --end-ms require --backtest")
    if args.backtest is None and args.market_slug:
        parser.error("--market-slug requires --backtest")
    if args.backtest is None and args.gap_policy is not None:
        parser.error("--gap-policy requires --backtest")
    if args.backtest is not None and args.dashboard is True:
        parser.error(BACKTEST_DASHBOARD_MESSAGE)
    bot = load_bot(args.bot, config)
    try:
        dashboard_enabled = _dashboard_enabled(
            args.dashboard if args.dashboard is not None else args.backtest is None
        )
    except ValueError as error:
        parser.error(str(error))
    try:
        if args.backtest is not None:
            try:
                options = BacktestOptions(
                    archive_path=args.backtest,
                    session_id=args.session,
                    start_at_ms=args.start_ms,
                    end_at_ms=args.end_ms,
                    market_slugs=tuple(args.market_slug),
                    seed=args.seed,
                    results_dir=args.results_dir,
                    report_interval_ms=args.report_interval_ms,
                    gap_policy=args.gap_policy or BacktestGapPolicy.STRICT,
                )
            except ValueError as error:
                parser.error(str(error))
            result = asyncio.run(
                run_backtest(
                    bot,
                    config,
                    bot_spec=args.bot,
                    options=options,
                )
            )
            _print_backtest_summary(result)
            try:
                print_performance_chart(result.results_dir)
            except PerformanceChartError as error:
                print(f"{BACKTEST_CHART_WARNING}: {error}", file=sys.stderr)
        else:
            asyncio.run(
                run_bot(
                    bot,
                    config,
                    observer=TerminalDashboard() if dashboard_enabled else None,
                    results_dir=args.results_dir,
                    bot_spec=args.bot,
                    report_interval_ms=args.report_interval_ms,
                )
            )
    except BacktestError as error:
        parser.error(f"{error.reason.value}: {error}")
    except PerformanceArtifactError as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        # asyncio.run lets the cancelled task finish its async cleanup first.
        # Treat the user's first Ctrl+C as a normal shutdown, not a failure.
        return 130 if args.backtest is not None else 0
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one Polymarket bot")
    parser.add_argument("--bot", required=True, help="bot factory as module:attribute")
    parser.add_argument("--dotenv", default=DEFAULT_DOTENV_PATH)
    parser.add_argument("--override", action="append", default=[], metavar="FIELD=VALUE")
    parser.add_argument(
        "--dashboard",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show the live paper dashboard (default for ordinary runs)",
    )
    parser.add_argument(
        "--backtest",
        type=Path,
        metavar="ARCHIVE",
        help="replay a Slice 9A SQLite recording instead of live market data",
    )
    parser.add_argument("--session", type=int, help="recording session ID")
    parser.add_argument("--start-ms", type=int, help="inclusive replay start")
    parser.add_argument("--end-ms", type=int, help="inclusive replay end")
    parser.add_argument(
        "--market-slug",
        action="append",
        default=[],
        help="limit replay to one market slug; may be repeated",
    )
    parser.add_argument(
        "--gap-policy",
        type=BacktestGapPolicy,
        choices=tuple(BacktestGapPolicy),
        default=None,
        help="coverage-gap handling for backtests (default: strict)",
    )
    parser.add_argument("--seed", type=int, default=0, help="deterministic replay seed")
    parser.add_argument(
        "--results-dir",
        type=Path,
        help="new directory for performance artifacts",
    )
    parser.add_argument(
        "--report-interval-ms",
        type=_positive_int,
        default=DEFAULT_REPORT_INTERVAL_MS,
        help="equity sampling interval (default: 1000)",
    )
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _print_backtest_summary(result: BacktestResult) -> None:
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


def _dashboard_enabled(value: bool) -> bool:
    interactive = (
        sys.stdout.isatty()
        and os.getenv(TERM_ENV_KEY, "").lower() != NON_INTERACTIVE_TERMINAL
    )
    if value is True and not interactive:
        raise ValueError(INTERACTIVE_TERMINAL_REQUIRED_MESSAGE)
    return value
