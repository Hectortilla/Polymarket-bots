"""Archive session rows, lifecycle transitions, and recovery."""

from __future__ import annotations

import sqlite3

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


def _insert_session(connection: sqlite3.Connection, started_at_ms: int) -> int:
    cursor = connection.execute(
        """
        INSERT INTO sessions (
            started_at_ms, integrity_status, recorder_version, sdk_version
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
        "SELECT * FROM sessions ORDER BY session_id DESC LIMIT 1"
    ).fetchone()
    return None if row is None else _session_from_row(row)


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
    raise ArchiveFormatError(
        f"recording session {normalized_session} does not exist"
    )


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
            """
            UPDATE sessions
            SET ended_at_ms = ?, clean_close = ?, integrity_status = ?,
                failure_reason = ?
            WHERE session_id = ?
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
        clean_close = row["clean_close"]
        if clean_close not in (0, 1):
            raise ValueError("invalid clean-close state")
        return RecordingSession(
            session_id=_strict_int(row["session_id"], "session ID"),
            started_at_ms=_strict_int(row["started_at_ms"], "session start"),
            ended_at_ms=_optional_strict_int(row["ended_at_ms"], "session end"),
            clean_close=bool(clean_close),
            integrity_status=SessionIntegrityStatus(row["integrity_status"]),
            recorder_version=_required_text(
                row["recorder_version"],
                "recorder version",
            ),
            sdk_version=_required_text(row["sdk_version"], "SDK version"),
            failure_reason=(
                None
                if row["failure_reason"] is None
                else _required_text(row["failure_reason"], "failure reason")
            ),
        )
    except (TypeError, ValueError) as error:
        raise ArchiveFormatError("recording session is malformed") from error
