"""Command-line inspector for local recording archives."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from .archive_errors import RecordingArchiveError
from .archive_models import RecordingEventCounts
from .contracts import CoverageGapRecord, SessionIntegrityStatus
from .inspection import RecordingInspection, inspect_recording


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
    print(f"Recording: {inspection.archive_path}")
    print(
        f"Archive: schema=v{inspection.schema_version} "
        f"size={_format_bytes(inspection.archive_size_bytes)}"
    )
    print(f"Target: {_format_target_identity(inspection.target_identity)}")
    if inspection.sidecar_size_bytes:
        print(f"SQLite sidecars: {_format_bytes(inspection.sidecar_size_bytes)}")
    anomaly_summary = str(inspection.known_anomaly_count)
    if inspection.anomaly_unavailable_session_count:
        anomaly_summary += (
            f" ({inspection.anomaly_unavailable_session_count} session(s) unavailable)"
        )
    print(
        "Summary: "
        f"sessions={len(inspection.sessions)} "
        f"markets={inspection.market_count} "
        f"captured={_format_duration(inspection.captured_duration_ms)} "
        f"events={inspection.replay_event_count:,} "
        f"checkpoints={inspection.checkpoint_count:,} "
        f"detected_gaps={inspection.gap_count} "
        f"open_gaps={inspection.open_gap_count} "
        f"capture_anomalies={anomaly_summary}"
    )
    if inspection.event_start_at_ms is not None:
        print(
            "Event range: "
            f"{_format_timestamp(inspection.event_start_at_ms)} -> "
            f"{_format_timestamp(inspection.event_end_at_ms)}"
        )

    print("\nSessions:")
    for session in inspection.sessions:
        statistics = session.statistics
        stored = statistics.event_counts.stored_event_count
        anomaly_count = statistics.capture_anomaly_count
        anomaly_text = "unavailable" if anomaly_count is None else str(anomaly_count)
        bounds = statistics.event_bounds
        range_text = (
            "no replay events"
            if bounds is None
            else (
                f"{_format_timestamp(bounds.start_at_ms)} -> "
                f"{_format_timestamp(bounds.end_at_ms)}"
            )
        )
        print(
            f"  {statistics.session.session_id}: "
            f"status={statistics.session.integrity_status.value} "
            f"captured={_format_duration(statistics.duration_ms)} "
            f"markets={len(statistics.markets)} "
            f"events={statistics.event_counts.replay_event_count:,} "
            f"stored_rows={stored:,} "
            f"checkpoints={statistics.checkpoint_count:,} "
            f"gaps={len(session.coverage_gaps)} "
            f"open_gaps={session.open_gap_count} "
            f"anomalies={anomaly_text}"
        )
        lifecycle_end = (
            "active"
            if statistics.session.ended_at_ms is None
            else _format_timestamp(statistics.session.ended_at_ms)
        )
        print(
            f"     session_window="
            f"{_format_timestamp(statistics.session.started_at_ms)} -> "
            f"{lifecycle_end}"
        )
        print(f"     event_range={range_text}")
        if statistics.session.failure_reason:
            print(f"     failure={statistics.session.failure_reason}")

    event_counts = _total_event_counts(inspection)
    print("\nEvent types:")
    print(
        "  "
        f"metadata={event_counts.market_metadata:,} "
        f"book_baselines={event_counts.book_baseline:,} "
        f"book_deltas={event_counts.book_delta:,} "
        f"public_trades={event_counts.public_trade:,} "
        f"tick_changes={event_counts.tick_size_change:,} "
        f"resolutions={event_counts.resolution:,} "
        f"gap_records={event_counts.coverage_gap:,}"
    )

    print("\nMarkets:")
    markets = tuple(
        (session.statistics.session.session_id, market)
        for session in inspection.sessions
        for market in session.statistics.markets
    )
    if not markets:
        print("  none")
    for session_id, market in markets:
        print(
            f"  session={session_id} "
            f"slug={market.market_slug} "
            f"captured={_format_duration(market.duration_ms)} "
            f"events={market.event_count:,} "
            f"condition={market.condition_id}"
        )

    if inspection.gap_count:
        print("\nCoverage gaps:")
        for session in inspection.sessions:
            for record in session.coverage_gaps:
                gap = record.gap
                gap_end = (
                    "open"
                    if gap.ended_at_ms is None
                    else _format_timestamp(gap.ended_at_ms)
                )
                print(
                    f"  session={record.session_id} "
                    f"gap={record.gap_id} "
                    f"reason={gap.reason.value} "
                    f"range={_format_timestamp(gap.started_at_ms)} -> {gap_end} "
                    f"scope={_format_gap_scope(record)}"
                )

    print("\nBacktest notes:")
    for note in _backtest_notes(inspection):
        print(f"  - {note}")


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


def _format_timestamp(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "n/a"
    return (
        datetime.fromtimestamp(timestamp_ms / 1_000, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _format_duration(duration_ms: int) -> str:
    remaining_seconds, milliseconds = divmod(duration_ms, 1_000)
    hours, remaining_seconds = divmod(remaining_seconds, 3_600)
    minutes, seconds = divmod(remaining_seconds, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    if milliseconds:
        parts.append(f"{seconds}.{milliseconds:03d}s")
    else:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _format_bytes(size_bytes: int) -> str:
    value = float(size_bytes)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1_024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1_024
    raise AssertionError("byte unit selection is unreachable")


def _format_target_identity(target_identity: str) -> str:
    try:
        value = json.loads(target_identity)
    except json.JSONDecodeError:
        return target_identity
    if not isinstance(value, dict):
        return target_identity
    if value.get("kind") == "bot" and isinstance(value.get("spec"), str):
        return f"bot {value['spec']}"
    market_slugs = value.get("market_slugs")
    if value.get("kind") == "static" and isinstance(market_slugs, list):
        if all(isinstance(slug, str) for slug in market_slugs):
            return "static " + ", ".join(market_slugs)
    return target_identity


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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
