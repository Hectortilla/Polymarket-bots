"""Single-writer lifecycle and durable append operations for recordings."""

from __future__ import annotations

import os
import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.errors import (
    ArchiveExistsError,
    ArchiveFormatError,
    ArchiveIntegrityError,
)
from polybot.recording.archive.features import _enable_capture_anomaly_journal
from polybot.recording.archive.format import _validate_archive
from polybot.recording.archive.lifecycle import (
    _archive_path,
    _release_writer_lock,
    open_exclusive_connection,
)
from polybot.recording.archive.paths import SQLITE_SIDECAR_SUFFIXES
from polybot.recording.archive.primitives import _nonnegative_timestamp, _required_text
from polybot.recording.archive.rows import _latest_metadata
from polybot.recording.archive.schema import (
    SCHEMA_VERSION,
    SESSIONS_TABLE,
    SQLITE_APPLICATION_ID,
    ensure_capture_anomaly_schema,
    initialize_archive_schema,
)
from polybot.recording.archive.sessions import (
    INTERRUPTED_SESSION_REASON,
    _insert_session,
    _latest_session,
)
from polybot.recording.archive.snapshot import _last_observed_at_ms, _last_sequence
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.session import SessionIntegrityStatus, SessionState


@dataclass(frozen=True, slots=True)
class ArchiveSession:
    path: Path
    connection: sqlite3.Connection
    lock_file: BinaryIO
    target_identity: str
    session_id: int
    session_started_at_ms: int
    next_sequence: int
    last_observed_at_ms: int | None
    resume_from_ms: int | None
    metadata_by_condition: dict[str, MarketMetadataPayload]
    has_gap: bool


def create_session(
    path: str | Path,
    *,
    target_identity: str,
    started_at_ms: int,
) -> ArchiveSession:
    archive_path = _archive_path(path)
    normalized_target = _required_text(target_identity, "target identity")
    _nonnegative_timestamp(started_at_ms, "session start")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            archive_path,
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
            0o600,
        )
    except FileExistsError as error:
        raise ArchiveExistsError(
            f"recording archive already exists: {archive_path}"
        ) from error
    os.close(descriptor)
    lock_file = None
    connection: sqlite3.Connection | None = None
    try:
        connection, lock_file = open_exclusive_connection(archive_path)
        initialize_archive_schema(
            connection,
            application_id=SQLITE_APPLICATION_ID,
            schema_version=SCHEMA_VERSION,
            target_identity=normalized_target,
            created_at_ms=started_at_ms,
        )
        connection.execute("BEGIN IMMEDIATE")
        ensure_capture_anomaly_schema(connection)
        session_id = _insert_session(connection, started_at_ms)
        _enable_capture_anomaly_journal(
            connection,
            available_from_session_id=session_id,
            enabled_at_ms=started_at_ms,
        )
        connection.commit()
        return ArchiveSession(
            path=archive_path,
            connection=connection,
            lock_file=lock_file,
            target_identity=normalized_target,
            session_id=session_id,
            session_started_at_ms=started_at_ms,
            next_sequence=1,
            last_observed_at_ms=None,
            resume_from_ms=None,
            metadata_by_condition={},
            has_gap=False,
        )
    except Exception:
        if connection is not None:
            connection.close()
        if lock_file is not None:
            _release_writer_lock(lock_file)
        with suppress(OSError):
            archive_path.unlink()
        for suffix in SQLITE_SIDECAR_SUFFIXES:
            with suppress(OSError):
                archive_path.with_name(f"{archive_path.name}{suffix}").unlink()
        raise


def resume_session(
    path: str | Path,
    *,
    target_identity: str,
    started_at_ms: int,
) -> ArchiveSession:
    archive_path = _archive_path(path)
    normalized_target = _required_text(target_identity, "target identity")
    _nonnegative_timestamp(started_at_ms, "session start")
    if not archive_path.is_file():
        raise ArchiveFormatError(f"recording archive does not exist: {archive_path}")
    lock_file = None
    connection: sqlite3.Connection | None = None
    try:
        connection, lock_file = open_exclusive_connection(archive_path)
        stored_target = _validate_archive(connection)
        if stored_target != normalized_target:
            raise ArchiveFormatError(
                "recording target identity does not match the existing archive"
            )
        prior_session = _latest_session(connection)
        if prior_session is None:
            raise ArchiveFormatError("recording archive has no sessions")
        last_observed = _last_observed_at_ms(connection)
        resume_from_ms = (
            prior_session.ended_at_ms
            if prior_session.ended_at_ms is not None
            else last_observed or prior_session.started_at_ms
        )
        if started_at_ms < resume_from_ms:
            raise ArchiveIntegrityError(
                "resume session starts before the previous recording boundary"
            )
        next_sequence = _last_sequence(connection) + 1
        metadata_by_condition = _latest_metadata(connection)
        connection.execute("BEGIN IMMEDIATE")
        ensure_capture_anomaly_schema(connection)
        if prior_session.integrity_status is SessionIntegrityStatus.ACTIVE:
            connection.execute(
                f"""
                UPDATE {SESSIONS_TABLE}
                SET {ArchiveColumn.ENDED_AT_MS} = ?, {ArchiveColumn.CLEAN_CLOSE} = ?, {ArchiveColumn.INTEGRITY_STATUS} = ?,
                    {ArchiveColumn.FAILURE_REASON} = ?
                WHERE {ArchiveColumn.SESSION_ID} = ?
                """,
                (
                    *SessionState.interrupted(
                        ended_at_ms=resume_from_ms,
                        failure_reason=INTERRUPTED_SESSION_REASON,
                    ).database_values(),
                    prior_session.session_id,
                ),
            )
        session_id = _insert_session(connection, started_at_ms)
        _enable_capture_anomaly_journal(
            connection,
            available_from_session_id=session_id,
            enabled_at_ms=started_at_ms,
        )
        connection.commit()
        return ArchiveSession(
            path=archive_path,
            connection=connection,
            lock_file=lock_file,
            target_identity=normalized_target,
            session_id=session_id,
            session_started_at_ms=started_at_ms,
            next_sequence=next_sequence,
            last_observed_at_ms=last_observed,
            resume_from_ms=resume_from_ms,
            metadata_by_condition=metadata_by_condition,
            has_gap=False,
        )
    except Exception:
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.rollback()
            connection.close()
        if lock_file is not None:
            _release_writer_lock(lock_file)
        raise
