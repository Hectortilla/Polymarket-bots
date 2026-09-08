"""Archive session rows, lifecycle transitions, and recovery."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import SESSIONS_TABLE

from ..contracts.session import SessionIntegrityStatus, SessionState
from .errors import ArchiveFormatError, RecordingArchiveError
from .models import RecordingSession
from .primitives import (
    _optional_strict_int,
    _positive_int,
    _required_text,
    _strict_int,
)
from .provenance import (
    RECORDER_DISTRIBUTION,
    SDK_DISTRIBUTION,
    distribution_version,
)
from .snapshot import _last_session_observed_at_ms

INTERRUPTED_SESSION_REASON = "recording process ended before a clean close"


def select_session(
    sessions: tuple[RecordingSession, ...],
    session_id: int | None = None,
) -> RecordingSession:
    """Select one archive session, requiring an ID when it is ambiguous."""

    if session_id is None:
        if len(sessions) != 1:
            raise ArchiveFormatError(
                "recording archive requires an explicit session ID"
            )
        return sessions[0]
    normalized_session = _positive_int(session_id, "session ID")
    for session in sessions:
        if session.session_id == normalized_session:
            return session
    raise ArchiveFormatError(f"recording session {normalized_session} does not exist")


def _insert_session(connection: sqlite3.Connection, started_at_ms: int) -> int:
    cursor = connection.execute(
        f"""
        INSERT INTO {SESSIONS_TABLE} (
            {ArchiveColumn.STARTED_AT_MS}, {ArchiveColumn.INTEGRITY_STATUS}, {ArchiveColumn.RECORDER_VERSION}, {ArchiveColumn.SDK_VERSION}
        ) VALUES (?, ?, ?, ?)
        """,
        (
            started_at_ms,
            SessionState.active().integrity_status.value,
            distribution_version(RECORDER_DISTRIBUTION),
            distribution_version(SDK_DISTRIBUTION),
        ),
    )
    return int(cursor.lastrowid)


def _latest_session(connection: sqlite3.Connection) -> RecordingSession | None:
    row = connection.execute(
        f"SELECT * FROM {SESSIONS_TABLE} ORDER BY {ArchiveColumn.SESSION_ID} DESC LIMIT 1"
    ).fetchone()
    return None if row is None else _session_from_row(row)


def _recover_interrupted_session(connection: sqlite3.Connection) -> None:
    session = _latest_session(connection)
    if session is None or session.integrity_status is not SessionIntegrityStatus.ACTIVE:
        return
    durable_end_at_ms = _last_session_observed_at_ms(
        connection,
        session.session_id,
    )
    ended_at_ms = max(
        session.started_at_ms,
        durable_end_at_ms or session.started_at_ms,
    )
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            f"""
            UPDATE {SESSIONS_TABLE}
            SET {ArchiveColumn.ENDED_AT_MS} = ?, {ArchiveColumn.CLEAN_CLOSE} = ?, {ArchiveColumn.INTEGRITY_STATUS} = ?,
                {ArchiveColumn.FAILURE_REASON} = ?
            WHERE {ArchiveColumn.SESSION_ID} = ?
            """,
            (
                *SessionState.interrupted(
                    ended_at_ms=ended_at_ms,
                    failure_reason=INTERRUPTED_SESSION_REASON,
                ).database_values(),
                session.session_id,
            ),
        )
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        raise RecordingArchiveError(
            "failed to recover interrupted recording session"
        ) from error


def _session_from_row(row: sqlite3.Row) -> RecordingSession:
    try:
        clean_close = row[ArchiveColumn.CLEAN_CLOSE]
        if clean_close not in (0, 1):
            raise ValueError("invalid clean-close state")
        return RecordingSession(
            session_id=_strict_int(row[ArchiveColumn.SESSION_ID], "session ID"),
            started_at_ms=_strict_int(
                row[ArchiveColumn.STARTED_AT_MS], "session start"
            ),
            ended_at_ms=_optional_strict_int(
                row[ArchiveColumn.ENDED_AT_MS], "session end"
            ),
            clean_close=bool(clean_close),
            integrity_status=SessionIntegrityStatus(
                row[ArchiveColumn.INTEGRITY_STATUS]
            ),
            recorder_version=_required_text(
                row[ArchiveColumn.RECORDER_VERSION],
                "recorder version",
            ),
            sdk_version=_required_text(row[ArchiveColumn.SDK_VERSION], "SDK version"),
            failure_reason=(
                None
                if row[ArchiveColumn.FAILURE_REASON] is None
                else _required_text(row[ArchiveColumn.FAILURE_REASON], "failure reason")
            ),
        )
    except (TypeError, ValueError) as error:
        raise ArchiveFormatError("recording session is malformed") from error
