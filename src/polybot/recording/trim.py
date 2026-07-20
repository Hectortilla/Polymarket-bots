"""Command-line entrypoint for safe recording-archive trimming."""

from __future__ import annotations

import argparse
from pathlib import Path

from polybot.backtesting.contracts import BacktestError

from .archive_errors import RecordingArchiveError
from .trim_contracts import (
    RecordingTrimError,
    RecordingTrimPlan,
    RecordingTrimResult,
)
from .trimming import trim_recording


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
    if not result.replaced:
        print(f"Dry run: archive not replaced: {plan.archive_path}")
        return

    print(f"Recording replaced: {plan.archive_path}")
    if result.backup_path is None:
        print("Warning: recording replaced without a backup (--no-backup).")
    else:
        print(f"Backup: {result.backup_path}")
    print(f"Trimmed size: {result.trimmed_size_bytes} bytes")


def _print_plan(plan: RecordingTrimPlan) -> None:
    print(
        "Trim plan: "
        f"session={plan.source_session.session_id} "
        f"start_ms={plan.start_at_ms} "
        f"end_ms={plan.end_at_ms} "
        f"duration_ms={plan.duration_ms}"
    )
    print(
        "Source: "
        f"retained_events={plan.source_event_count} "
        f"selected_session_gaps={plan.source_gap_count} "
        f"archive_size_bytes={plan.source_size_bytes}",
        flush=True,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
