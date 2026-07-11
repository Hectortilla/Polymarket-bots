"""Command-line argument parsing and bot startup."""

from __future__ import annotations

import argparse
import asyncio

from bots.framework.config import BotConfig

from .config import load_dotenv, parse_overrides
from .factories import load_bot
from .runner import run_bot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Polymarket bot in paper mode")
    parser.add_argument("--bot", required=True, help="bot factory as module:attribute")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument("--override", action="append", default=[], metavar="FIELD=VALUE")
    args = parser.parse_args(argv)
    load_dotenv(args.dotenv)
    overrides = parse_overrides(args.override)
    config = BotConfig.from_env(args.bot.rsplit(":", 1)[-1]).with_overrides(**overrides)
    bot = load_bot(args.bot, config)
    asyncio.run(run_bot(bot, config))
    return 0
