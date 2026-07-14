"""Command-line argument parsing and bot startup."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from polybot.framework.config.models import BotConfig

from .config import load_dotenv, parse_overrides
from .dashboard.controller import TerminalDashboard
from .factories import load_bot
from .runner.service import run_bot

INTERACTIVE_TERMINAL_REQUIRED_MESSAGE = (
    "dashboard requires an interactive terminal; use --no-dashboard for headless runs"
)
TERM_ENV_KEY = "TERM"
NON_INTERACTIVE_TERMINAL = "dumb"

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Polymarket bot in paper mode")
    parser.add_argument("--bot", required=True, help="bot factory as module:attribute")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--override", action="append", default=[], metavar="FIELD=VALUE")
    parser.add_argument(
        "--dashboard",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="show the live terminal dashboard (default; use --no-dashboard for headless mode)",
    )
    args = parser.parse_args(argv)
    load_dotenv(args.dotenv)
    overrides = parse_overrides(args.override)
    config = BotConfig.from_env(args.bot.rsplit(":", 1)[-1]).with_overrides(**overrides)
    bot = load_bot(args.bot, config)
    try:
        dashboard_enabled = _dashboard_enabled(args.dashboard)
    except ValueError as error:
        parser.error(str(error))
    try:
        asyncio.run(
            run_bot(
                bot,
                config,
                observer=TerminalDashboard() if dashboard_enabled else None,
            )
        )
    except KeyboardInterrupt:
        # asyncio.run lets the cancelled task finish its async cleanup first.
        # Treat the user's first Ctrl+C as a normal shutdown, not a failure.
        return 0
    return 0


def _dashboard_enabled(value: bool) -> bool:
    interactive = (
        sys.stdout.isatty()
        and os.getenv(TERM_ENV_KEY, "").lower() != NON_INTERACTIVE_TERMINAL
    )
    if value is True and not interactive:
        raise ValueError(INTERACTIVE_TERMINAL_REQUIRED_MESSAGE)
    return value
