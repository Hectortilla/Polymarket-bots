"""Command-line entrypoint for historical market recording."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from datetime import datetime
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from polybot.cli.config import DEFAULT_DOTENV_PATH, load_dotenv, parse_overrides
from polybot.cli.factories import load_bot
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.recording.archive.paths import RECORDING_ARCHIVE_SUFFIX

from .duration import parse_duration_seconds
from .identity import bot_target_identity, static_target_identity
from .planning import StaticStreamPlanProvider
from .service.recorder import record_markets
from .terminal import ACCENT_STYLE, SUCCESS_STYLE, WARNING_STYLE, recording_console


RECORDING_CONFIG_NAME = "market-recorder"
DEFAULT_RECORDINGS_DIR = Path("recordings")
DEFAULT_RECORDINGS_DIR_ENV = "DEFAULT_RECORDINGS_DIR"


def recordings_dir_from_env() -> Path:
    """Return the recording directory configured for this process."""
    configured_dir = os.environ.get(DEFAULT_RECORDINGS_DIR_ENV)
    return Path(configured_dir) if configured_dir else DEFAULT_RECORDINGS_DIR


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
    return (
        recordings_dir
        / timestamp
        / f"{description or 'recording'}{RECORDING_ARCHIVE_SUFFIX}"
    )


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
    config = config.without_sensitive_values().with_overrides(
        mode=BotMode.PAPER,
        live_enabled=False,
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
            recordings_dir=recordings_dir_from_env(),
        )
    )
    target_identity = (
        bot_target_identity(bot_spec, config)
        if bot_spec is not None
        else static_target_identity(market_slugs)
    )
    _print_recording_start(
        output_path=output_path,
        bot_spec=bot_spec,
        market_slugs=market_slugs,
        duration_seconds=args.duration,
        resume=args.resume,
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
        recording_console().print(
            Panel.fit(
                "[bold yellow]Recording interrupted[/]\n"
                f"[dim]Committed data remains at[/] {output_path}",
                border_style=WARNING_STYLE,
                title="[bold]Market recorder[/]",
            )
        )
        return 0
    recording_console().print(
        Panel.fit(
            "[bold green]Recording complete[/]\n"
            f"[dim]Archive[/] {output_path}",
            border_style=SUCCESS_STYLE,
            title="[bold]Market recorder[/]",
        )
    )
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
            "DEFAULT_RECORDINGS_DIR/<timestamp>/<description>.sqlite3 "
            "(or recordings/... when unset)"
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
    parser.add_argument("--dotenv", default=DEFAULT_DOTENV_PATH)
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
    )
    return parser


def _print_recording_start(
    *,
    output_path: Path,
    bot_spec: str | None,
    market_slugs: tuple[str, ...],
    duration_seconds: int | None,
    resume: bool,
) -> None:
    details = Table.grid(padding=(0, 1))
    details.add_column(style="bold")
    details.add_column(overflow="fold")
    if bot_spec is not None:
        details.add_row("Planning", f"Bot: {bot_spec}")
    else:
        details.add_row("Planning", f"Static: {', '.join(market_slugs)}")
    details.add_row("Output", str(output_path))
    details.add_row(
        "Run time",
        "Until interrupted"
        if duration_seconds is None
        else f"{duration_seconds:,} seconds",
    )
    details.add_row("Mode", "Resume existing archive" if resume else "New archive")
    recording_console().print(
        Panel(
            details,
            border_style=ACCENT_STYLE,
            title="[bold bright_cyan]Market recorder[/]",
        )
    )
