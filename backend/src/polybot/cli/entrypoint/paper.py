from __future__ import annotations

import argparse
import asyncio
import os
import sys

from polybot.cli.dashboard.controller import TerminalDashboard
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.runtime import run_bot

INTERACTIVE_TERMINAL_REQUIRED_MESSAGE = (
    "dashboard requires an interactive terminal; use --no-dashboard for headless runs"
)
TERM_ENV_KEY = "TERM"
NON_INTERACTIVE_TERMINAL = "dumb"
DASHBOARD_OPTION = "--dashboard"


def run_paper_mode(
    bot: BaseBot,
    config: BotConfig,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    try:
        dashboard_enabled = _dashboard_enabled(
            args.dashboard if args.dashboard is not None else True
        )
    except ValueError as error:
        parser.error(str(error))
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


def add_paper_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        DASHBOARD_OPTION,
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show the live paper dashboard (default for ordinary runs)",
    )


def _dashboard_enabled(value: bool) -> bool:
    interactive = (
        sys.stdout.isatty()
        and os.getenv(TERM_ENV_KEY, "").lower() != NON_INTERACTIVE_TERMINAL
    )
    if value is True and not interactive:
        raise ValueError(INTERACTIVE_TERMINAL_REQUIRED_MESSAGE)
    return value
