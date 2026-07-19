"""Command-line entrypoint for historical market recording."""

from __future__ import annotations

import argparse
import asyncio
import re
from datetime import datetime
from pathlib import Path

from polybot.cli.config import load_dotenv, parse_overrides
from polybot.cli.factories import load_bot
from polybot.framework.config.models import BotConfig, BotMode

from .duration import parse_duration_seconds
from .identity import bot_target_identity, static_target_identity
from .planning import StaticStreamPlanProvider
from .service import record_markets


RECORDING_CONFIG_NAME = "market-recorder"
DEFAULT_RECORDINGS_DIR = Path("recordings")


def default_output_path(
    *,
    bot_spec: str | None,
    market_slugs: tuple[str, ...],
    now: datetime | None = None,
    recordings_dir: Path = DEFAULT_RECORDINGS_DIR,
) -> Path:
    """Return the conventional timestamped path for a new recording."""
    timestamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    if bot_spec is not None:
        module, _, factory = bot_spec.rpartition(":")
        description = f"bot-{module.rsplit('.', 1)[-1] or factory}"
    elif len(market_slugs) == 1:
        description = f"market-{market_slugs[0]}"
    else:
        description = "markets"
    description = re.sub(r"[^A-Za-z0-9._-]+", "-", description).strip("-.")
    return recordings_dir / timestamp / f"{description or 'recording'}.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    if args.resume and args.output is None:
        parser.error("--resume requires --output")
    load_dotenv(args.dotenv)

    bot_spec: str | None = args.bot
    config_name = (
        bot_spec.rsplit(":", 1)[-1] if bot_spec is not None else RECORDING_CONFIG_NAME
    )
    overrides = parse_overrides(args.override)
    config = BotConfig.from_env(config_name).with_overrides(**overrides)
    config = config.with_overrides(
        mode=BotMode.PAPER,
        live_enabled=False,
        private_key=None,
        api_key=None,
        api_secret=None,
        api_passphrase=None,
        funder_address=None,
    )
    bot = load_bot(bot_spec, config) if bot_spec is not None else None
    market_slugs = (
        ()
        if bot_spec is not None
        else StaticStreamPlanProvider(tuple(args.market_slug)).market_slugs
    )
    output_path = (
        Path(args.output)
        if args.output is not None
        else default_output_path(
            bot_spec=bot_spec,
            market_slugs=market_slugs,
        )
    )
    target_identity = (
        bot_target_identity(bot_spec, config)
        if bot_spec is not None
        else static_target_identity(market_slugs)
    )

    try:
        asyncio.run(
            record_markets(
                config,
                output_path=output_path,
                target_identity=target_identity,
                bot=bot,
                market_slugs=market_slugs,
                duration_seconds=args.duration,
                resume=args.resume,
            )
        )
    except KeyboardInterrupt:
        return 0
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record normalized Polymarket market data for later replay"
    )
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--bot", help="bot factory used only for stream planning")
    targets.add_argument(
        "--market-slug",
        action="append",
        default=[],
        metavar="SLUG",
        help="static market slug to record; repeat for multiple markets",
    )
    parser.add_argument(
        "--output",
        help=(
            "SQLite archive path; defaults to "
            "recordings/<timestamp>/<description>.sqlite3"
        ),
    )
    parser.add_argument(
        "--duration",
        type=parse_duration_seconds,
        metavar="DURATION",
        help="optional run time such as 30m, 1d, or 10d",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume a compatible existing archive and record the offline gap",
    )
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
    )
    return parser
