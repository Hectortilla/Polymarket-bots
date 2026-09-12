from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from polybot.backtesting.contracts import BacktestOptions
from polybot.backtesting.policy import BacktestGapPolicy
from polybot.backtesting.validation import backtest_config_issue
from polybot.cli.backtest_command import execute_backtest
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig

BACKTEST_DASHBOARD_MESSAGE = "backtests are headless; omit --dashboard"
BACKTEST_OPTION = "--backtest"
SESSION_OPTION = "--session"
START_MS_OPTION = "--start-ms"
END_MS_OPTION = "--end-ms"
MARKET_SLUG_OPTION = "--market-slug"
GAP_POLICY_OPTION = "--gap-policy"
SEED_OPTION = "--seed"


def run_backtest_mode(
    bot: BaseBot,
    config: BotConfig,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
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
    asyncio.run(execute_backtest(bot, config, bot_spec=args.bot, options=options))


def validate_backtest_arguments(
    args: argparse.Namespace, config: BotConfig, parser: argparse.ArgumentParser
) -> None:
    if args.backtest is not None and (issue := backtest_config_issue(config)):
        parser.error(issue)
    if args.backtest is None and any(
        value is not None for value in (args.session, args.start_ms, args.end_ms)
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


def add_backtest_arguments(parser: argparse.ArgumentParser) -> None:
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
