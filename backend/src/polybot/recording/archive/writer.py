"""Single-writer lifecycle and durable append operations for recordings."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import BinaryIO

from polybot.framework.clock import system_now_ms

from ..contracts.book import BookBaselinePayload
from ..contracts.records import (
    BookCheckpoint,
    CaptureAnomalyRecord,
    RecordedEvent,
)
from ..contracts.anomalies import CaptureAnomalyPayload
from ..contracts.gaps import CoverageGapPayload
from ..contracts.market import (
    MarketIdentity,
    MarketMetadataPayload,
)
from ..contracts.payloads import event_token_ids
from ..contracts.kinds import PayloadKind
from ..contracts.session import SessionIntegrityStatus, SessionState
from ..serialization.entrypoints import (
    capture_anomaly_json,
    payload_json,
)
from ..serialization.registry import payload_kind
from .connections import configure_writer_connection
from .errors import (
    ArchiveClosedError,
    ArchiveExistsError,
    ArchiveFormatError,
    ArchiveIntegrityError,
    RecordingArchiveError,
)
from .features import _enable_capture_anomaly_journal
from .format import _validate_archive
from .integrity import _invalidate_gap_baselines, _validate_event_dependencies
from .lifecycle import (
    _acquire_writer_lock,
    _archive_path,
    _open_connection,
    _open_writer_lock_file,
    _release_writer_lock,
)
from .paths import SQLITE_SIDECAR_SUFFIXES
from .primitives import (
    _nonnegative_int,
    _nonnegative_timestamp,
    _positive_int,
    _required_text,
)
from .rows import _latest_metadata, _typed_payload
from .schema import (
    CAPTURE_ANOMALIES_TABLE,
    SCHEMA_VERSION,
    SQLITE_APPLICATION_ID,
    ensure_capture_anomaly_schema,
    initialize_archive_schema,
)
from .sessions import (
    INTERRUPTED_SESSION_REASON,
    _insert_session,
    _latest_session,
)
from .snapshot import _last_observed_at_ms, _last_sequence


class RecordingArchive:
    """Single-writer recording archive with process and thread serialization."""

    def __init__(
        self,
        *,
        path: Path,
        connection: sqlite3.Connection,
        lock_file: BinaryIO,
        target_identity: str,
        session_id: int,
        session_started_at_ms: int,
        next_sequence: int,
        last_observed_at_ms: int | None,
        resume_from_ms: int | None,
        metadata_by_condition: dict[str, MarketMetadataPayload],
        has_gap: bool,
    ) -> None:
        self._path = path
        self._connection = connection
        self._lock_file = lock_file
        self._target_identity = target_identity
        self._session_id = session_id
        self._session_started_at_ms = session_started_at_ms
        self._next_sequence = next_sequence
        self._last_observed_at_ms = last_observed_at_ms
        self._resume_from_ms = resume_from_ms
        self._metadata_by_condition = metadata_by_condition
        self._baseline_generations: set[tuple[int, str]] = set()
        self._has_gap = has_gap
        self._closed = False
        self._lock = RLock()

    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        target_identity: str,
        started_at_ms: int,
    ) -> RecordingArchive:
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
        lock_file = _open_writer_lock_file(archive_path)
        connection: sqlite3.Connection | None = None
        try:
            _acquire_writer_lock(lock_file, archive_path)
            connection = _open_connection(archive_path)
            configure_writer_connection(connection)
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
            return cls(
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
            _release_writer_lock(lock_file)
            with suppress(OSError):
                archive_path.unlink()
            for suffix in SQLITE_SIDECAR_SUFFIXES:
                with suppress(OSError):
                    archive_path.with_name(f"{archive_path.name}{suffix}").unlink()
            raise

    @classmethod
    def resume(
        cls,
        path: str | Path,
        *,
        target_identity: str,
        started_at_ms: int,
    ) -> RecordingArchive:
        archive_path = _archive_path(path)
        normalized_target = _required_text(target_identity, "target identity")
        _nonnegative_timestamp(started_at_ms, "session start")
        if not archive_path.is_file():
            raise ArchiveFormatError(
                f"recording archive does not exist: {archive_path}"
            )
        lock_file = _open_writer_lock_file(archive_path)
        connection: sqlite3.Connection | None = None
        try:
            _acquire_writer_lock(lock_file, archive_path)
            connection = _open_connection(archive_path)
            configure_writer_connection(connection)
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
                    """
                    UPDATE sessions
                    SET ended_at_ms = ?, clean_close = ?, integrity_status = ?,
                        failure_reason = ?
                    WHERE session_id = ?
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
            return cls(
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
            _release_writer_lock(lock_file)
            raise

    @property
    def path(self) -> Path:
        return self._path

    @property
    def target_identity(self) -> str:
        return self._target_identity

    @property
    def session_id(self) -> int:
        return self._session_id

    @property
    def next_sequence(self) -> int:
        with self._lock:
            self._ensure_open()
            return self._next_sequence

    @property
    def next_subscription_generation(self) -> int:
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT COALESCE(MAX(subscription_generation), -1) + 1 FROM events"
            ).fetchone()
            return int(row[0])

    @property
    def resume_from_ms(self) -> int | None:
        return self._resume_from_ms

    @property
    def last_observed_at_ms(self) -> int | None:
        with self._lock:
            self._ensure_open()
            return self._last_observed_at_ms

    def append_event(self, event: RecordedEvent) -> None:
        self.append_events((event,))

    def append_events(self, events: Iterable[RecordedEvent]) -> None:
        pending = tuple(events)
        if not pending:
            return
        with self._lock:
            self._ensure_open()
            metadata = self._metadata_by_condition.copy()
            baselines = self._baseline_generations.copy()
            last_observed = self._last_observed_at_ms
            expected_sequence = self._next_sequence
            has_gap = self._has_gap
            for event in pending:
                if not isinstance(event, RecordedEvent):
                    raise ArchiveIntegrityError(
                        "archive can store only RecordedEvent values"
                    )
                if event.session_id != self._session_id:
                    raise ArchiveIntegrityError(
                        "recorded event belongs to a different recording session"
                    )
                if event.sequence != expected_sequence:
                    raise ArchiveIntegrityError(
                        "expected recording sequence "
                        f"{expected_sequence}, got {event.sequence}"
                    )
                if last_observed is not None and event.observed_at_ms < last_observed:
                    raise ArchiveIntegrityError(
                        "recorded event observation timestamps must be nondecreasing"
                    )
                _validate_event_dependencies(event, metadata, baselines)
                if isinstance(event.payload, MarketMetadataPayload):
                    metadata[event.payload.condition_id] = event.payload
                elif isinstance(event.payload, BookBaselinePayload):
                    baselines.add(
                        (event.subscription_generation, event.payload.token_id)
                    )
                elif isinstance(event.payload, CoverageGapPayload):
                    has_gap = True
                    _invalidate_gap_baselines(
                        event.payload,
                        metadata,
                        baselines,
                        identity=event.identity,
                    )
                expected_sequence += 1
                last_observed = event.observed_at_ms
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                for event in pending:
                    self._insert_event(event)
                self._connection.commit()
            except (sqlite3.Error, ValueError) as error:
                self._connection.rollback()
                raise RecordingArchiveError(
                    "failed to append recording events"
                ) from error
            self._metadata_by_condition = metadata
            self._baseline_generations = baselines
            self._last_observed_at_ms = last_observed
            self._next_sequence = expected_sequence
            self._has_gap = has_gap

    def append_metadata(self, event: RecordedEvent) -> None:
        if not isinstance(event.payload, MarketMetadataPayload):
            raise ArchiveIntegrityError("metadata append requires a metadata event")
        self.append_event(event)

    def append_gap(self, event: RecordedEvent) -> int:
        if not isinstance(event.payload, CoverageGapPayload):
            raise ArchiveIntegrityError("gap append requires a coverage-gap event")
        with self._lock:
            self.append_event(event)
            self._ensure_open()
            row = self._connection.execute(
                "SELECT gap_id FROM coverage_gaps WHERE event_sequence = ?",
                (event.sequence,),
            ).fetchone()
            if row is None:
                raise ArchiveIntegrityError("coverage gap was not indexed")
            return int(row[0])

    def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        _positive_int(gap_id, "coverage gap ID")
        _nonnegative_timestamp(ended_at_ms, "coverage gap end")
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                """
                SELECT event_sequence, payload_json
                FROM coverage_gaps
                WHERE gap_id = ?
                """,
                (gap_id,),
            ).fetchone()
            if row is None:
                raise ArchiveIntegrityError(f"unknown coverage gap ID {gap_id}")
            payload = _typed_payload(
                PayloadKind.COVERAGE_GAP,
                row["payload_json"],
                CoverageGapPayload,
            )
            if payload.ended_at_ms is not None:
                raise ArchiveIntegrityError("coverage gap is already closed")
            closed_payload = replace(payload, ended_at_ms=ended_at_ms)
            serialized = payload_json(closed_payload)
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    """
                    UPDATE coverage_gaps
                    SET ended_at_ms = ?, payload_json = ?
                    WHERE gap_id = ?
                    """,
                    (ended_at_ms, serialized, gap_id),
                )
                self._connection.execute(
                    "UPDATE events SET payload_json = ? WHERE sequence = ?",
                    (serialized, row["event_sequence"]),
                )
                self._connection.commit()
            except sqlite3.Error as error:
                self._connection.rollback()
                raise RecordingArchiveError("failed to close coverage gap") from error

    def append_capture_anomaly(
        self,
        anomaly: CaptureAnomalyPayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity,
        subscription_generation: int,
    ) -> CaptureAnomalyRecord:
        """Journal diagnostics without adding a canonical replay event."""

        if not isinstance(anomaly, CaptureAnomalyPayload):
            raise ArchiveIntegrityError(
                "capture anomaly append requires a capture anomaly payload"
            )
        if not isinstance(identity, MarketIdentity):
            raise ArchiveIntegrityError("capture anomaly identity is invalid")
        _nonnegative_timestamp(observed_at_ms, "capture anomaly observation")
        _nonnegative_int(
            subscription_generation,
            "capture anomaly subscription generation",
        )
        if not anomaly.matches_index_identity(identity):
            raise ArchiveIntegrityError(
                "capture anomaly identity does not match its initial fragment"
            )
        serialized = capture_anomaly_json(anomaly)
        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                cursor = self._connection.execute(
                    f"""
                    INSERT INTO {CAPTURE_ANOMALIES_TABLE} (
                        session_id, subscription_generation, observed_at_ms,
                        condition_id, market_slug, token_id, failure_kind,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._session_id,
                        subscription_generation,
                        observed_at_ms,
                        identity.condition_id,
                        identity.market_slug,
                        identity.token_id,
                        anomaly.failure_kind.value,
                        serialized,
                    ),
                )
                anomaly_id = int(cursor.lastrowid)
                self._connection.commit()
            except (sqlite3.Error, ValueError) as error:
                self._connection.rollback()
                raise RecordingArchiveError(
                    "failed to append capture anomaly"
                ) from error
            return CaptureAnomalyRecord(
                anomaly_id=anomaly_id,
                session_id=self._session_id,
                subscription_generation=subscription_generation,
                observed_at_ms=observed_at_ms,
                identity=identity,
                anomaly=anomaly,
            )

    def append_checkpoint(self, checkpoint: BookCheckpoint) -> None:
        self.append_checkpoints((checkpoint,))

    def append_checkpoints(self, checkpoints: Iterable[BookCheckpoint]) -> None:
        pending = tuple(checkpoints)
        if not pending:
            return
        with self._lock:
            self._ensure_open()
            last_sequence = self._next_sequence - 1
            last_observed = self._last_observed_at_ms
            for checkpoint in pending:
                if not isinstance(checkpoint, BookCheckpoint):
                    raise ArchiveIntegrityError(
                        "archive can store only BookCheckpoint values"
                    )
                if checkpoint.session_id != self._session_id:
                    raise ArchiveIntegrityError(
                        "checkpoint belongs to a different recording session"
                    )
                if checkpoint.sequence > last_sequence:
                    raise ArchiveIntegrityError(
                        "checkpoint cannot reference an uncommitted event sequence"
                    )
                if (
                    last_observed is not None
                    and checkpoint.observed_at_ms < last_observed
                ):
                    raise ArchiveIntegrityError(
                        "checkpoint observation timestamps must be nondecreasing"
                    )
                condition_id = checkpoint.identity.condition_id
                if (
                    condition_id is None
                    or condition_id not in self._metadata_by_condition
                ):
                    raise ArchiveIntegrityError(
                        "checkpoint requires previously committed market metadata"
                    )
                market = self._metadata_by_condition[condition_id]
                if (
                    checkpoint.identity.market_slug != market.market_slug
                    or checkpoint.book.token_id
                    not in {outcome.token_id for outcome in market.outcomes}
                ):
                    raise ArchiveIntegrityError(
                        "checkpoint identity does not match committed market metadata"
                    )
                baseline_key = (
                    checkpoint.subscription_generation,
                    checkpoint.book.token_id,
                )
                if baseline_key not in self._baseline_generations:
                    raise ArchiveIntegrityError(
                        "checkpoint requires a baseline in its subscription generation"
                    )
                last_observed = checkpoint.observed_at_ms
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.executemany(
                    """
                    INSERT INTO book_checkpoints (
                        token_id, sequence, session_id, subscription_generation,
                        observed_at_ms, condition_id, market_slug, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            checkpoint.book.token_id,
                            checkpoint.sequence,
                            checkpoint.session_id,
                            checkpoint.subscription_generation,
                            checkpoint.observed_at_ms,
                            checkpoint.identity.condition_id,
                            checkpoint.identity.market_slug,
                            payload_json(checkpoint.book),
                        )
                        for checkpoint in pending
                    ),
                )
                self._connection.commit()
            except (sqlite3.Error, ValueError) as error:
                self._connection.rollback()
                raise RecordingArchiveError(
                    "failed to append book checkpoints"
                ) from error
            self._last_observed_at_ms = last_observed

    def close(
        self,
        *,
        clean: bool = True,
        failure_reason: str | None = None,
        ended_at_ms: int | None = None,
    ) -> None:
        with self._lock:
            if self._closed:
                return
            if clean and failure_reason is not None:
                raise ValueError("clean archive close cannot include a failure reason")
            if not clean:
                failure_reason = (
                    _required_text(failure_reason, "failure reason")
                    if failure_reason is not None
                    else "recording writer failed"
                )
            durable_boundary_ms = max(
                self._session_started_at_ms,
                self._last_observed_at_ms or 0,
            )
            if ended_at_ms is None:
                ended_at_ms = (
                    max(durable_boundary_ms, system_now_ms())
                    if clean
                    else durable_boundary_ms
                )
            else:
                _nonnegative_timestamp(ended_at_ms, "archive end")
                if ended_at_ms < durable_boundary_ms:
                    raise ValueError(
                        "archive end cannot precede its durable boundary"
                    )
            session_state = (
                SessionState.cleanly_closed(
                    ended_at_ms=ended_at_ms,
                    has_coverage_gap=self._has_gap,
                )
                if clean
                else SessionState.failed(
                    ended_at_ms=ended_at_ms,
                    failure_reason=failure_reason,
                )
            )
            close_error: Exception | None = None
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    """
                    UPDATE sessions
                    SET ended_at_ms = ?, clean_close = ?, integrity_status = ?,
                        failure_reason = ?
                    WHERE session_id = ?
                    """,
                    (*session_state.database_values(), self._session_id),
                )
                self._connection.commit()
                self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as error:
                with suppress(sqlite3.Error):
                    self._connection.rollback()
                close_error = RecordingArchiveError(
                    "failed to finalize recording archive"
                )
                close_error.__cause__ = error
            finally:
                try:
                    self._connection.close()
                finally:
                    _release_writer_lock(self._lock_file)
                    self._closed = True
            if close_error is not None:
                raise close_error

    def __enter__(self) -> RecordingArchive:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc is None:
            self.close()
        else:
            self.close(clean=False, failure_reason=f"{type(exc).__name__}: {exc}")

    def _insert_event(self, event: RecordedEvent) -> None:
        identity = event.identity
        kind = payload_kind(event.payload)
        serialized = payload_json(event.payload)
        self._connection.execute(
            """
            INSERT INTO events (
                sequence, session_id, subscription_generation, observed_at_ms,
                source_timestamp_ms, condition_id, market_slug, token_id,
                payload_kind, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.sequence,
                event.session_id,
                event.subscription_generation,
                event.observed_at_ms,
                event.source_timestamp_ms,
                None if identity is None else identity.condition_id,
                None if identity is None else identity.market_slug,
                None if identity is None else identity.token_id,
                kind.value,
                serialized,
            ),
        )
        self._connection.executemany(
            "INSERT INTO event_tokens (sequence, token_id) VALUES (?, ?)",
            ((event.sequence, token_id) for token_id in event_token_ids(event.payload)),
        )
        if isinstance(event.payload, MarketMetadataPayload):
            self._connection.execute(
                """
                INSERT INTO metadata_revisions (
                    condition_id, sequence, observed_at_ms, payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    event.payload.condition_id,
                    event.sequence,
                    event.observed_at_ms,
                    serialized,
                ),
            )
        elif isinstance(event.payload, CoverageGapPayload):
            self._connection.execute(
                """
                INSERT INTO coverage_gaps (
                    event_sequence, session_id, subscription_generation,
                    observed_at_ms, condition_id, market_slug, started_at_ms,
                    ended_at_ms, reason, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.sequence,
                    event.session_id,
                    event.subscription_generation,
                    event.observed_at_ms,
                    None if identity is None else identity.condition_id,
                    None if identity is None else identity.market_slug,
                    event.payload.started_at_ms,
                    event.payload.ended_at_ms,
                    event.payload.reason,
                    serialized,
                ),
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArchiveClosedError("recording archive is closed")
