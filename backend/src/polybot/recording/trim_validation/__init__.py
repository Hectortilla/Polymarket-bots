from __future__ import annotations

from pathlib import Path

from polybot.backtesting.contracts import BacktestOptions
from polybot.backtesting.selection import ReplaySelectionResolver
from polybot.backtesting.selection.coverage import SelectionCoverage
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.trim_contracts import RecordingTrimError, RecordingTrimPlan
from polybot.recording.trim_validation.timeline import validate_trimmed_rows


def validate_trimmed_archive(
    path: Path,
    plan: RecordingTrimPlan,
    *,
    expected_event_count: int,
) -> None:
    with RecordingReader.for_replay(path) as reader:
        sessions = reader.sessions()
        if len(sessions) != 1:
            raise RecordingTrimError(
                "trimmed recording does not contain exactly one session"
            )
        session = sessions[0]
        if (
            session.started_at_ms != plan.start_at_ms
            or session.ended_at_ms != plan.end_at_ms
        ):
            raise RecordingTrimError(
                "trimmed recording session bounds do not match the selected interval"
            )
        if reader.coverage_gaps():
            raise RecordingTrimError(
                "trimmed recording unexpectedly contains coverage gaps"
            )
        selection = ReplaySelectionResolver(reader).resolve(
            session,
            BacktestOptions(archive_path=path),
        )
        SelectionCoverage(reader).validate_indexes(selection)
        if selection.market_slugs != plan.market_slugs:
            raise RecordingTrimError(
                "trimmed recording market selection changed during export"
            )
        if (
            selection.start_at_ms != plan.start_at_ms
            or selection.end_at_ms != plan.end_at_ms
        ):
            raise RecordingTrimError(
                "trimmed recording default range changed during export"
            )
        event_count = validate_trimmed_rows(path, reader, session)
        if event_count != expected_event_count:
            raise RecordingTrimError(
                "trimmed recording event count changed during export"
            )
