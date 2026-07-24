"""Diagnostic capture-anomaly queries for immutable archive snapshots."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from ..contracts.anomalies import CaptureFailureKind
from ..contracts.records import CaptureAnomalyRecord
from .errors import ArchiveFormatError, CaptureAnomalyJournalUnavailableError
from .lifecycle import _open_readonly_connection
from .models import RecordingFeatureProvenance, RecordingSession
from .primitives import (
    _nonnegative_timestamp,
    _required_text,
)
from .rows import _capture_anomaly_from_row
from .schema import CAPTURE_ANOMALIES_TABLE
from .sessions import select_session


def select_overlapping_recording_sessions(
    sessions: tuple[RecordingSession, ...],
    *,
    start_at_ms: int | None,
    end_at_ms: int | None,
    session_id: int | None,
) -> tuple[RecordingSession, ...]:
    if session_id is not None:
        return tuple(
            session for session in sessions if session.session_id == session_id
        )
    return tuple(
        session
        for session in sessions
        if (end_at_ms is None or session.started_at_ms <= end_at_ms)
        and (
            start_at_ms is None
            or session.ended_at_ms is None
            or session.ended_at_ms >= start_at_ms
        )
    )


def capture_anomaly_journal_available(
    sessions: tuple[RecordingSession, ...],
    provenance: RecordingFeatureProvenance | None,
    session_id: int,
) -> bool:
    """Return whether diagnostic rows are available for one selected session."""

    selected_session = select_session(sessions, session_id)
    return (
        provenance is not None
        and selected_session.session_id >= provenance.available_from_session_id
    )


def iter_capture_anomalies(
    *,
    path: Path,
    immutable: bool,
    sessions: tuple[RecordingSession, ...],
    replay_cutoff_id: int,
    provenance: RecordingFeatureProvenance | None,
    start_at_ms: int | None = None,
    end_at_ms: int | None = None,
    session_id: int | None = None,
    condition_id: str | None = None,
    market_slug: str | None = None,
    failure_kind: CaptureFailureKind | str | None = None,
) -> Iterator[CaptureAnomalyRecord]:
    """Stream filtered quarantined diagnostics from one reader snapshot."""

    if start_at_ms is not None:
        _nonnegative_timestamp(start_at_ms, "capture anomaly selection start")
    if end_at_ms is not None:
        _nonnegative_timestamp(end_at_ms, "capture anomaly selection end")
    if (
        start_at_ms is not None
        and end_at_ms is not None
        and end_at_ms < start_at_ms
    ):
        raise ValueError("capture anomaly selection cannot end before it starts")
    normalized_session = (
        None if session_id is None else select_session(sessions, session_id).session_id
    )
    normalized_condition = (
        None
        if condition_id is None
        else _required_text(condition_id, "condition ID")
    )
    normalized_slug = (
        None if market_slug is None else _required_text(market_slug, "market slug")
    )
    if failure_kind is None:
        normalized_failure = None
    else:
        try:
            normalized_failure = CaptureFailureKind(failure_kind)
        except (TypeError, ValueError) as error:
            raise ValueError("capture anomaly failure kind is invalid") from error
    selected_sessions = select_overlapping_recording_sessions(
        sessions,
        start_at_ms=start_at_ms,
        end_at_ms=end_at_ms,
        session_id=normalized_session,
    )
    require_capture_anomaly_journal(provenance, selected_sessions)
    clauses = ["anomaly_id <= ?"]
    parameters: list[object] = [replay_cutoff_id]
    for column, value, operator in (
        ("observed_at_ms", start_at_ms, ">="),
        ("observed_at_ms", end_at_ms, "<="),
        ("session_id", normalized_session, "="),
        ("condition_id", normalized_condition, "="),
        ("market_slug", normalized_slug, "="),
        (
            "failure_kind",
            None if normalized_failure is None else normalized_failure.value,
            "=",
        ),
    ):
        if value is not None:
            clauses.append(f"{column} {operator} ?")
            parameters.append(value)
    return stream_capture_anomalies(
        path=path,
        immutable=immutable,
        clauses=clauses,
        parameters=tuple(parameters),
    )


def require_capture_anomaly_journal(
    provenance: RecordingFeatureProvenance | None,
    selected_sessions: tuple[RecordingSession, ...],
) -> None:
    """Reject diagnostic queries outside the feature's activation boundary."""

    if provenance is None:
        raise CaptureAnomalyJournalUnavailableError(
            "capture anomaly diagnostics are unavailable for this archive"
        )
    unavailable = tuple(
        session.session_id
        for session in selected_sessions
        if session.session_id < provenance.available_from_session_id
    )
    if unavailable:
        session_list = ", ".join(str(value) for value in unavailable)
        raise CaptureAnomalyJournalUnavailableError(
            "capture anomaly diagnostics are unavailable for recording "
            f"sessions: {session_list}"
        )


def stream_capture_anomalies(
    *,
    path: Path,
    immutable: bool,
    clauses: list[str],
    parameters: tuple[object, ...],
) -> Iterator[CaptureAnomalyRecord]:
    """Open a short-lived snapshot and stream validated diagnostic rows."""

    connection = _open_readonly_connection(path, immutable=immutable)
    try:
        connection.execute("BEGIN")
        cursor = connection.execute(
            f"SELECT * FROM {CAPTURE_ANOMALIES_TABLE} WHERE "
            + " AND ".join(clauses)
            + " ORDER BY anomaly_id",
            parameters,
        )
    except sqlite3.Error as error:
        connection.close()
        raise ArchiveFormatError("capture anomaly journal is malformed") from error

    def iterate() -> Iterator[CaptureAnomalyRecord]:
        try:
            for row in cursor:
                yield _capture_anomaly_from_row(row)
        except sqlite3.Error as error:
            raise ArchiveFormatError("capture anomaly journal is malformed") from error
        finally:
            connection.close()

    return iterate()
