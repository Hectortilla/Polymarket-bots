"""Command-line entrypoint for safe recording-archive trimming."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from polybot.backtesting.contracts import BacktestError

from .archive.errors import RecordingArchiveError
from .trim_contracts import (
    RecordingTrimError,
    RecordingTrimPlan,
    RecordingTrimResult,
)
from .trimming import trim_recording
from .terminal import (
    ACCENT_STYLE,
    SUCCESS_STYLE,
    WARNING_STYLE,
    format_bytes,
    format_duration,
    recording_console,
)


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    try:
        result = trim_recording(
            args.archive,
            session_id=args.session,
            dry_run=args.dry_run,
            keep_backup=not args.no_backup,
            on_plan=_print_plan,
        )
    except (RecordingTrimError, RecordingArchiveError, BacktestError) as error:
        parser.error(str(error))

    _print_result(result)
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replace a recording with its longest all-market gap-free interval"
        )
    )
    parser.add_argument("archive", type=Path, metavar="ARCHIVE")
    parser.add_argument(
        "--session",
        type=_positive_int,
        help="source recording session ID; required when multiple sessions exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the selected interval without replacing the archive",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="replace the archive without retaining the default backup",
    )
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _print_result(result: RecordingTrimResult) -> None:
    plan = result.plan
    console = recording_console()
    if not result.replaced:
        console.print(
            Panel.fit(
                f"[bold {WARNING_STYLE}]Dry run complete[/]\n"
                f"[dim]Archive unchanged[/]: {plan.archive_path}",
                border_style=WARNING_STYLE,
                title="[bold]Recording trim[/]",
            )
        )
        return

    details = Table.grid(padding=(0, 1))
    details.add_column(style="bold")
    details.add_column(overflow="fold")
    details.add_row("Archive", str(plan.archive_path))
    details.add_row("Trimmed size", format_bytes(result.trimmed_size_bytes))
    if result.backup_path is None:
        details.add_row(
            "Backup",
            f"[{WARNING_STYLE}]Not retained (--no-backup)[/]",
        )
    else:
        details.add_row("Backup", str(result.backup_path))
    console.print(
        Panel(
            details,
            border_style=SUCCESS_STYLE,
            title=f"[bold {SUCCESS_STYLE}]Recording trim complete[/]",
        )
    )


def _print_plan(plan: RecordingTrimPlan) -> None:
    table = Table(show_header=True, header_style=f"bold {ACCENT_STYLE}")
    table.add_column("Session", justify="right")
    table.add_column("Clean interval", no_wrap=True)
    table.add_column("Duration", justify="right")
    table.add_column("Retained events", justify="right")
    table.add_column("Source gaps", justify="right")
    table.add_column("Archive size", justify="right")
    table.add_row(
        str(plan.source_session.session_id),
        f"{plan.start_at_ms} → {plan.end_at_ms}",
        format_duration(plan.duration_ms),
        f"{plan.source_event_count:,}",
        str(plan.source_gap_count),
        format_bytes(plan.source_size_bytes),
    )
    recording_console().print(
        Panel(table, border_style=ACCENT_STYLE, title="[bold]Trim plan[/]"),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
