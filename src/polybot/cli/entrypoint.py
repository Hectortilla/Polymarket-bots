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
)
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.performance.artifacts.errors import PerformanceArtifactError
from polybot.performance.contracts.sampling import DEFAULT_REPORT_INTERVAL_MS

from .backtest_command import execute_backtest
from .config import DEFAULT_DOTENV_PATH, load_dotenv, parse_overrides
from .dashboard.controller import TerminalDashboard
from .factories import load_bot
from polybot.runtime import run_bot

INTERACTIVE_TERMINAL_REQUIRED_MESSAGE = (
    "dashboard requires an interactive terminal; use --no-dashboard for headless runs"
)
TERM_ENV_KEY = "TERM"
NON_INTERACTIVE_TERMINAL = "dumb"
BACKTEST_DASHBOARD_MESSAGE = "backtests are headless; omit --dashboard"
BOT_OPTION = "--bot"
DOTENV_OPTION = "--dotenv"
OVERRIDE_OPTION = "--override"
DASHBOARD_OPTION = "--dashboard"
BACKTEST_OPTION = "--backtest"
SESSION_OPTION = "--session"
START_MS_OPTION = "--start-ms"
END_MS_OPTION = "--end-ms"
MARKET_SLUG_OPTION = "--market-slug"
GAP_POLICY_OPTION = "--gap-policy"
SEED_OPTION = "--seed"
RESULTS_DIR_OPTION = "--results-dir"
REPORT_INTERVAL_OPTION = "--report-interval-ms"


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
        parser.error(
            f"{SESSION_OPTION}, {START_MS_OPTION}, and {END_MS_OPTION} "
            f"require {BACKTEST_OPTION}"
        )
    if args.backtest is None and args.market_slug:
        parser.error(f"{MARKET_SLUG_OPTION} requires {BACKTEST_OPTION}")
    if args.backtest is None and args.gap_policy is not None:
        parser.error(f"{GAP_POLICY_OPTION} requires {BACKTEST_OPTION}")
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
            asyncio.run(
                execute_backtest(
                    bot,
                    config,
                    bot_spec=args.bot,
                    options=options,
                )
            )
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
    parser.add_argument(BOT_OPTION, required=True, help="bot factory as module:attribute")
    parser.add_argument(DOTENV_OPTION, default=DEFAULT_DOTENV_PATH)
    parser.add_argument(
        OVERRIDE_OPTION,
        action="append",
        default=[],
        metavar="FIELD=VALUE",
    )
    parser.add_argument(
        DASHBOARD_OPTION,
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show the live paper dashboard (default for ordinary runs)",
    )
    parser.add_argument(
        BACKTEST_OPTION,
        type=Path,
        metavar="ARCHIVE",
        help="replay a Slice 9A SQLite recording instead of live market data",
    )
    parser.add_argument(SESSION_OPTION, type=int, help="recording session ID")
    parser.add_argument(START_MS_OPTION, type=int, help="inclusive replay start")
    parser.add_argument(END_MS_OPTION, type=int, help="inclusive replay end")
    parser.add_argument(
        MARKET_SLUG_OPTION,
        action="append",
        default=[],
        help="limit replay to one market slug; may be repeated",
    )
    parser.add_argument(
        GAP_POLICY_OPTION,
        type=BacktestGapPolicy,
        choices=tuple(BacktestGapPolicy),
        default=None,
        help="coverage-gap handling for backtests (default: strict)",
    )
    parser.add_argument(
        SEED_OPTION,
        type=int,
        default=0,
        help="deterministic replay seed",
    )
    parser.add_argument(
        RESULTS_DIR_OPTION,
        type=Path,
        help="new directory for performance artifacts",
    )
    parser.add_argument(
        REPORT_INTERVAL_OPTION,
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


def _dashboard_enabled(value: bool) -> bool:
    interactive = (
        sys.stdout.isatty()
        and os.getenv(TERM_ENV_KEY, "").lower() != NON_INTERACTIVE_TERMINAL
    )
    if value is True and not interactive:
        raise ValueError(INTERACTIVE_TERMINAL_REQUIRED_MESSAGE)
    return value
