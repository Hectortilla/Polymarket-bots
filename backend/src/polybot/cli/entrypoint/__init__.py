"""Shared command-line configuration and mode dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path

from polybot.backtesting.contracts import BacktestError
from polybot.cli.arguments import positive_int
from polybot.cli.config import DEFAULT_DOTENV_PATH, load_dotenv, parse_overrides
from polybot.cli.factories import load_bot
from polybot.framework.config.models import BotConfig
from polybot.performance.artifacts.errors import PerformanceArtifactError
from polybot.performance.contracts.sampling import DEFAULT_REPORT_INTERVAL_MS

from .backtest import (
    add_backtest_arguments,
    run_backtest_mode,
    validate_backtest_arguments,
)
from .paper import add_paper_arguments, run_paper_mode

BOT_OPTION = "--bot"
DOTENV_OPTION = "--dotenv"
OVERRIDE_OPTION = "--override"
RESULTS_DIR_OPTION = "--results-dir"
REPORT_INTERVAL_OPTION = "--report-interval-ms"


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    load_dotenv(args.dotenv)
    overrides = parse_overrides(args.override)
    config = BotConfig.from_env(args.bot.rsplit(":", 1)[-1]).with_overrides(**overrides)
    validate_backtest_arguments(args, config, parser)
    bot = load_bot(args.bot, config)
    try:
        if args.backtest is not None:
            run_backtest_mode(bot, config, args, parser)
        else:
            run_paper_mode(bot, config, args, parser)
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
    parser.add_argument(
        BOT_OPTION, required=True, help="bot factory as module:attribute"
    )
    parser.add_argument(DOTENV_OPTION, default=DEFAULT_DOTENV_PATH)
    parser.add_argument(
        OVERRIDE_OPTION,
        action="append",
        default=[],
        metavar="FIELD=VALUE",
    )
    add_paper_arguments(parser)
    add_backtest_arguments(parser)

    parser.add_argument(
        RESULTS_DIR_OPTION,
        type=Path,
        help="new directory for performance artifacts",
    )
    parser.add_argument(
        REPORT_INTERVAL_OPTION,
        type=positive_int,
        default=DEFAULT_REPORT_INTERVAL_MS,
        help=f"equity sampling interval (default: {DEFAULT_REPORT_INTERVAL_MS})",
    )
    return parser
