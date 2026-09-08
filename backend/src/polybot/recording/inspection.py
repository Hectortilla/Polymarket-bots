"""Read-only recording archive inspection contracts and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .archive.models import RecordingEventCounts, RecordingSessionStatistics
from .archive.paths import SQLITE_SIDECAR_SUFFIXES
from .archive.reader import RecordingReader
from .contracts.records import CoverageGapRecord
from .contracts.session import SessionIntegrityStatus


@dataclass(frozen=True, slots=True)
class RecordingSessionInspection:
    statistics: RecordingSessionStatistics
    coverage_gaps: tuple[CoverageGapRecord, ...]

    @property
    def open_gap_count(self) -> int:
        return sum(gap.is_open for gap in self.coverage_gaps)


@dataclass(frozen=True, slots=True)
class RecordingInspection:
    archive_path: Path
    archive_size_bytes: int
    sidecar_size_bytes: int
    schema_version: int
    target_identity: str
    sessions: tuple[RecordingSessionInspection, ...]

    @property
    def market_count(self) -> int:
        return len(
            {
                market.condition_id
                for session in self.sessions
                for market in session.statistics.markets
            }
        )

    @property
    def captured_duration_ms(self) -> int:
        return sum(session.statistics.duration_ms for session in self.sessions)

    @property
    def replay_event_count(self) -> int:
        return self.event_counts.replay_event_count

    @property
    def event_counts(self) -> RecordingEventCounts:
        return RecordingEventCounts.combine(
            session.statistics.event_counts for session in self.sessions
        )

    @property
    def checkpoint_count(self) -> int:
        return sum(session.statistics.checkpoint_count for session in self.sessions)

    @property
    def gap_count(self) -> int:
        return sum(len(session.coverage_gaps) for session in self.sessions)

    @property
    def open_gap_count(self) -> int:
        return sum(session.open_gap_count for session in self.sessions)

    @property
    def known_anomaly_count(self) -> int:
        return sum(
            session.statistics.capture_anomaly_count or 0 for session in self.sessions
        )

    @property
    def anomaly_unavailable_session_count(self) -> int:
        return sum(
            session.statistics.capture_anomaly_count is None
            for session in self.sessions
        )

    @property
    def event_start_at_ms(self) -> int | None:
        starts = tuple(
            bounds.start_at_ms
            for session in self.sessions
            if (bounds := session.statistics.event_bounds) is not None
        )
        return min(starts) if starts else None

    @property
    def event_end_at_ms(self) -> int | None:
        ends = tuple(
            bounds.end_at_ms
            for session in self.sessions
            if (bounds := session.statistics.event_bounds) is not None
        )
        return max(ends) if ends else None

    def backtest_readiness_notes(
        self,
    ) -> tuple[str, ...]:
        notes: list[str] = []
        if len(self.sessions) > 1:
            notes.append("Backtesting requires an explicit --session selection.")
        active_sessions = tuple(
            session.statistics.session.session_id
            for session in self.sessions
            if session.statistics.session.integrity_status
            is SessionIntegrityStatus.ACTIVE
        )
        if active_sessions:
            notes.append(
                "Active session(s) "
                + ", ".join(str(value) for value in active_sessions)
                + " are snapshot-only here; stop the recorder before backtesting."
            )
        partial_sessions = tuple(
            session.statistics.session.session_id
            for session in self.sessions
            if session.statistics.session.integrity_status
            in (SessionIntegrityStatus.INCOMPLETE, SessionIntegrityStatus.FAILED)
        )
        if partial_sessions:
            notes.append(
                "Partial source session(s): "
                + ", ".join(str(value) for value in partial_sessions)
                + ". Replay defaults to each durable boundary."
            )
        if self.gap_count:
            notes.append(
                "Detected gaps require a clean selected range; use recording.trim to "
                "retain the longest all-market clean interval."
            )
        else:
            notes.append(
                "No detected gaps. This does not prove exchange-complete capture."
            )
        if self.replay_event_count == 0:
            notes.append("The archive has no replay events.")
        notes.append(
            "The backtester still validates metadata, two-token book bootstrap, "
            "range, and selected-market coverage before running a bot."
        )
        return tuple(notes)


def inspect_recording(path: str | Path) -> RecordingInspection:
    """Return a validated, immutable snapshot summary of one local archive."""

    archive_path = Path(path).expanduser().resolve()
    with RecordingReader(archive_path) as reader:
        statistics = reader.statistics()
        sessions = tuple(
            RecordingSessionInspection(
                statistics=session,
                coverage_gaps=reader.coverage_gaps(
                    session_id=session.session.session_id
                ),
            )
            for session in statistics
        )
        schema_version = reader.schema_version
        target_identity = reader.target_identity
    return RecordingInspection(
        archive_path=archive_path,
        archive_size_bytes=archive_path.stat().st_size,
        sidecar_size_bytes=sum(
            sidecar.stat().st_size
            for suffix in SQLITE_SIDECAR_SUFFIXES
            if (
                sidecar := archive_path.with_name(f"{archive_path.name}{suffix}")
            ).is_file()
        ),
        schema_version=schema_version,
        target_identity=target_identity,
        sessions=sessions,
    )
