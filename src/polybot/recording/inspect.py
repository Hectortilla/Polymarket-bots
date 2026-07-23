"""Command-line inspector for local recording archives."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .archive.errors import RecordingArchiveError
from .archive.models import RecordingEventCounts
from .contracts.records import CoverageGapRecord
from .contracts.session import SessionIntegrityStatus
from .inspection import RecordingInspection, inspect_recording
from .identity import describe_target_identity
from .terminal import (
    ACCENT_STYLE,
    DANGER_STYLE,
    MUTED_STYLE,
    SUCCESS_STYLE,
    WARNING_STYLE,
    format_bytes,
    format_duration,
    format_timestamp,
    recording_console,
)


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    try:
        inspection = inspect_recording(args.archive)
    except (OSError, RecordingArchiveError, ValueError) as error:
        parser.error(str(error))
    _print_inspection(inspection)
    return 0


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize a recording before selecting it for backtesting"
    )
    parser.add_argument("archive", type=Path, metavar="ARCHIVE")
    return parser


def _print_inspection(inspection: RecordingInspection) -> None:
    console = recording_console()
    console.print(_archive_panel(inspection))
    console.print(_summary_panel(inspection))
    console.print(_sessions_panel(inspection))
    console.print(_event_mix_panel(inspection))
    console.print(_markets_panel(inspection))
    coverage_gaps_panel = _coverage_gaps_panel(inspection)
    if coverage_gaps_panel is not None:
        console.print(coverage_gaps_panel)
    console.print(_backtest_notes_panel(inspection))


def _archive_panel(inspection: RecordingInspection) -> Panel:
    """Build the archive identity and physical-size panel."""
    archive = Table.grid(padding=(0, 1))
    archive.add_column(style="bold")
    archive.add_column(overflow="fold")
    archive.add_row("Recording", str(inspection.archive_path))
    archive.add_row("Target", describe_target_identity(inspection.target_identity))
    archive.add_row("Schema", f"v{inspection.schema_version}")
    archive.add_row("Archive size", format_bytes(inspection.archive_size_bytes))
    if inspection.sidecar_size_bytes:
        archive.add_row("SQLite sidecars", format_bytes(inspection.sidecar_size_bytes))
    if inspection.event_start_at_ms is not None:
        archive.add_row(
            "Event range",
            f"{format_timestamp(inspection.event_start_at_ms)} → "
            f"{format_timestamp(inspection.event_end_at_ms)}",
        )
    return Panel(
        archive,
        border_style=ACCENT_STYLE,
        title="[bold bright_cyan]Recording inspector[/]",
    )


def _summary_panel(inspection: RecordingInspection) -> Panel:
    """Build the aggregate replay-readiness summary."""
    anomaly_summary = str(inspection.known_anomaly_count)
    if inspection.anomaly_unavailable_session_count:
        anomaly_summary += (
            f" ({inspection.anomaly_unavailable_session_count} session(s) unavailable)"
        )
    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column(justify="right")
    summary.add_column(style="bold")
    summary.add_column(justify="right")
    summary.add_row(
        "Sessions",
        str(len(inspection.sessions)),
        "Markets",
        str(inspection.market_count),
    )
    summary.add_row(
        "Captured time",
        format_duration(inspection.captured_duration_ms),
        "Replay events",
        f"{inspection.replay_event_count:,}",
    )
    summary.add_row(
        "Checkpoints",
        f"{inspection.checkpoint_count:,}",
        "Detected gaps",
        str(inspection.gap_count),
    )
    summary.add_row(
        "Open gaps",
        str(inspection.open_gap_count),
        "Capture anomalies",
        anomaly_summary,
    )
    return Panel(summary, border_style=ACCENT_STYLE, title="[bold]Summary[/]")


def _sessions_panel(inspection: RecordingInspection) -> Panel:
    """Build the per-session integrity table."""
    sessions = Table(header_style=f"bold {ACCENT_STYLE}")
    sessions.add_column("ID", justify="right")
    sessions.add_column("Status")
    sessions.add_column("Time", justify="right")
    sessions.add_column("Markets", justify="right")
    sessions.add_column("Events", justify="right")
    sessions.add_column("CPs", justify="right")
    sessions.add_column("Gaps", justify="right")
    sessions.add_column("Anoms", justify="right")
    for session in inspection.sessions:
        statistics = session.statistics
        anomaly_count = statistics.capture_anomaly_count
        anomaly_text = "unavailable" if anomaly_count is None else str(anomaly_count)
        status = statistics.session.integrity_status
        sessions.add_row(
            str(statistics.session.session_id),
            Text(status.value, style=_session_style(status)),
            format_duration(statistics.duration_ms),
            str(len(statistics.markets)),
            f"{statistics.event_counts.replay_event_count:,}",
            f"{statistics.checkpoint_count:,}",
            _gap_cell(session.open_gap_count, len(session.coverage_gaps)),
            anomaly_text,
        )
    return Panel(sessions, border_style=ACCENT_STYLE, title="[bold]Sessions[/]")


def _event_mix_panel(inspection: RecordingInspection) -> Panel:
    """Build the aggregate event-kind table."""
    event_counts = _total_event_counts(inspection)
    event_types = Table(header_style=f"bold {ACCENT_STYLE}")
    event_types.add_column("Meta", justify="right")
    event_types.add_column("Bases", justify="right")
    event_types.add_column("Deltas", justify="right")
    event_types.add_column("Trades", justify="right")
    event_types.add_column("Ticks", justify="right")
    event_types.add_column("Resolved", justify="right")
    event_types.add_column("Gaps", justify="right")
    event_types.add_row(
        f"{event_counts.market_metadata:,}",
        f"{event_counts.book_baseline:,}",
        f"{event_counts.book_delta:,}",
        f"{event_counts.public_trade:,}",
        f"{event_counts.tick_size_change:,}",
        f"{event_counts.resolution:,}",
        f"{event_counts.coverage_gap:,}",
    )
    return Panel(
        event_types,
        border_style=ACCENT_STYLE,
        title="[bold]Event mix[/]",
    )


def _markets_panel(inspection: RecordingInspection) -> Panel:
    """Build the captured-market table across all sessions."""
    markets = tuple(
        (session.statistics.session.session_id, market)
        for session in inspection.sessions
        for market in session.statistics.markets
    )
    market_table = Table(header_style=f"bold {ACCENT_STYLE}")
    market_table.add_column("Session", justify="right")
    market_table.add_column("Market slug")
    market_table.add_column("Captured", justify="right")
    market_table.add_column("Events", justify="right")
    market_table.add_column("Condition ID", style=MUTED_STYLE)
    if not markets:
        market_table.add_row("–", "No markets", "–", "–", "–")
    for session_id, market in markets:
        market_table.add_row(
            str(session_id),
            market.market_slug,
            format_duration(market.duration_ms),
            f"{market.event_count:,}",
            market.condition_id,
        )
    return Panel(market_table, border_style=ACCENT_STYLE, title="[bold]Markets[/]")


def _coverage_gaps_panel(inspection: RecordingInspection) -> Panel | None:
    """Build the optional coverage-gap detail table."""
    if not inspection.gap_count:
        return None
    gaps = Table(header_style=f"bold {WARNING_STYLE}")
    gaps.add_column("Session", justify="right")
    gaps.add_column("Gap", justify="right")
    gaps.add_column("Reason")
    gaps.add_column("Interval")
    gaps.add_column("Scope")
    for session in inspection.sessions:
        for record in session.coverage_gaps:
            gap = record.gap
            gap_end = (
                "open"
                if gap.ended_at_ms is None
                else format_timestamp(gap.ended_at_ms)
            )
            gaps.add_row(
                str(record.session_id),
                str(record.gap_id),
                gap.reason.value,
                f"{format_timestamp(gap.started_at_ms)} → {gap_end}",
                _format_gap_scope(record),
            )
    return Panel(gaps, border_style=WARNING_STYLE, title="[bold]Coverage gaps[/]")


def _backtest_notes_panel(inspection: RecordingInspection) -> Panel:
    """Build the action-oriented replay-readiness notes."""
    notes = "\n".join(f"• {note}" for note in _backtest_notes(inspection))
    return Panel(
        notes,
        border_style=WARNING_STYLE if inspection.gap_count else SUCCESS_STYLE,
        title="[bold]Backtest notes[/]",
    )


def _total_event_counts(inspection: RecordingInspection) -> RecordingEventCounts:
    counts = tuple(
        session.statistics.event_counts for session in inspection.sessions
    )
    return RecordingEventCounts(
        market_metadata=sum(value.market_metadata for value in counts),
        book_baseline=sum(value.book_baseline for value in counts),
        book_delta=sum(value.book_delta for value in counts),
        public_trade=sum(value.public_trade for value in counts),
        tick_size_change=sum(value.tick_size_change for value in counts),
        resolution=sum(value.resolution for value in counts),
        coverage_gap=sum(value.coverage_gap for value in counts),
    )


def _backtest_notes(inspection: RecordingInspection) -> tuple[str, ...]:
    notes: list[str] = []
    if len(inspection.sessions) > 1:
        notes.append("Backtesting requires an explicit --session selection.")
    active_sessions = tuple(
        session.statistics.session.session_id
        for session in inspection.sessions
        if session.statistics.session.integrity_status is SessionIntegrityStatus.ACTIVE
    )
    if active_sessions:
        notes.append(
            "Active session(s) "
            + ", ".join(str(value) for value in active_sessions)
            + " are snapshot-only here; stop the recorder before backtesting."
        )
    partial_sessions = tuple(
        session.statistics.session.session_id
        for session in inspection.sessions
        if session.statistics.session.integrity_status
        in (SessionIntegrityStatus.INCOMPLETE, SessionIntegrityStatus.FAILED)
    )
    if partial_sessions:
        notes.append(
            "Partial source session(s): "
            + ", ".join(str(value) for value in partial_sessions)
            + ". Replay defaults to each durable boundary."
        )
    if inspection.gap_count:
        notes.append(
            "Detected gaps require a clean selected range; use recording.trim to "
            "retain the longest all-market clean interval."
        )
    else:
        notes.append(
            "No detected gaps. This does not prove exchange-complete capture."
        )
    if inspection.replay_event_count == 0:
        notes.append("The archive has no replay events.")
    notes.append(
        "The backtester still validates metadata, two-token book bootstrap, "
        "range, and selected-market coverage before running a bot."
    )
    return tuple(notes)


def _format_gap_scope(record: CoverageGapRecord) -> str:
    gap = record.gap
    if gap.affected_market_slugs:
        return ",".join(gap.affected_market_slugs)
    if record.identity is not None and record.identity.market_slug is not None:
        return record.identity.market_slug
    if gap.affected_condition_ids:
        return f"{len(gap.affected_condition_ids)} condition(s)"
    if gap.affected_token_ids:
        return f"{len(gap.affected_token_ids)} token(s)"
    return "all target markets"


def _session_style(status: SessionIntegrityStatus) -> str:
    if status is SessionIntegrityStatus.COMPLETE:
        return SUCCESS_STYLE
    if status is SessionIntegrityStatus.FAILED:
        return DANGER_STYLE
    return WARNING_STYLE


def _gap_cell(open_gaps: int, total_gaps: int) -> Text:
    if open_gaps:
        return Text(f"{total_gaps} ({open_gaps} open)", style=DANGER_STYLE)
    if total_gaps:
        return Text(str(total_gaps), style=WARNING_STYLE)
    return Text("0", style=SUCCESS_STYLE)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
