"""Durable SQLite storage and strict readers for market recordings."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import RLock
from typing import BinaryIO
from urllib.parse import quote

from .contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    BookDeltaPayload,
    CaptureAnomalyPayload,
    CaptureAnomalyRecord,
    CaptureFailureKind,
    CoverageGapPayload,
    CoverageGapRecord,
    MarketIdentity,
    MarketMetadataPayload,
    RecordedEvent,
    ResolutionPayload,
    SessionIntegrityStatus,
    event_token_ids,
)
from .serialization import (
    PayloadKind,
    capture_anomaly_from_json,
    capture_anomaly_json,
    payload_from_json,
    payload_json,
    payload_kind,
)


SCHEMA_VERSION = 2
SQLITE_APPLICATION_ID = 0x504F4C59
RECORDER_DISTRIBUTION = "polymarket-polybot"
SDK_DISTRIBUTION = "polymarket-client"
INTERRUPTED_SESSION_REASON = "recording process ended before a clean close"
CAPTURE_ANOMALY_JOURNAL_FEATURE = "capture_anomaly_journal"


class RecordingArchiveError(RuntimeError):
    """Base error for recording persistence failures."""


class ArchiveExistsError(RecordingArchiveError):
    pass


class ArchiveLockedError(RecordingArchiveError):
    pass


class ArchiveFormatError(RecordingArchiveError):
    pass


class ArchiveIntegrityError(RecordingArchiveError):
    pass


class ArchiveCoverageError(RecordingArchiveError):
    pass


class ArchiveClosedError(RecordingArchiveError):
    pass


class CaptureAnomalyJournalUnavailableError(RecordingArchiveError):
    """The selected session predates capture-anomaly diagnostics."""


@dataclass(frozen=True, slots=True)
class RecordingSession:
    session_id: int
    started_at_ms: int
    ended_at_ms: int | None
    clean_close: bool
    integrity_status: SessionIntegrityStatus
    recorder_version: str
    sdk_version: str
    failure_reason: str | None


@dataclass(frozen=True, slots=True)
class RecordingEventBounds:
    """First and last event coordinates for one immutable reader selection."""

    first_sequence: int
    last_sequence: int
    start_at_ms: int
    end_at_ms: int


@dataclass(frozen=True, slots=True)
class RecordingFeatureProvenance:
    feature_name: str
    available_from_session_id: int
    enabled_at_ms: int
    recorder_version: str


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
            _configure_writer(connection)
            _initialize_schema(
                connection,
                target_identity=normalized_target,
                created_at_ms=started_at_ms,
            )
            connection.execute("BEGIN IMMEDIATE")
            _ensure_capture_anomaly_schema(connection)
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
            with suppress(OSError):
                archive_path.with_name(f"{archive_path.name}-wal").unlink()
            with suppress(OSError):
                archive_path.with_name(f"{archive_path.name}-shm").unlink()
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
            _configure_writer(connection)
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
            _ensure_capture_anomaly_schema(connection)
            if prior_session.integrity_status is SessionIntegrityStatus.ACTIVE:
                connection.execute(
                    """
                    UPDATE sessions
                    SET ended_at_ms = ?, integrity_status = ?, failure_reason = ?
                    WHERE session_id = ?
                    """,
                    (
                        resume_from_ms,
                        SessionIntegrityStatus.INCOMPLETE.value,
                        INTERRUPTED_SESSION_REASON,
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
                    """
                    INSERT INTO capture_anomalies (
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
            status = (
                SessionIntegrityStatus.INCOMPLETE
                if clean and self._has_gap
                else SessionIntegrityStatus.COMPLETE
                if clean
                else SessionIntegrityStatus.FAILED
            )
            durable_boundary_ms = max(
                self._session_started_at_ms,
                self._last_observed_at_ms or 0,
            )
            ended_at_ms = (
                max(durable_boundary_ms, time.time_ns() // 1_000_000)
                if clean
                else durable_boundary_ms
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
                    (
                        ended_at_ms,
                        int(clean),
                        status.value,
                        failure_reason,
                        self._session_id,
                    ),
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


class RecordingReader:
    """Read and validate one supported recording archive."""

    def __init__(
        self,
        path: str | Path,
        *,
        _replay_lock_file: BinaryIO | None = None,
    ) -> None:
        self._path = _archive_path(path)
        self._replay_lock_file = _replay_lock_file
        self._immutable = self._replay_lock_file is not None
        if not self._path.is_file():
            if self._replay_lock_file is not None:
                _release_writer_lock(self._replay_lock_file)
            raise ArchiveFormatError(f"recording archive does not exist: {self._path}")
        self._lock = RLock()
        self._closed = False
        connection: sqlite3.Connection | None = None
        try:
            connection = _open_readonly_connection(
                self._path,
                immutable=self._immutable,
            )
            self._connection = connection
            self._target_identity = _validate_archive(self._connection)
            self._connection.execute("BEGIN")
            self._replay_cutoff_sequence = _last_sequence(self._connection)
            self._sessions = tuple(
                _session_from_row(row)
                for row in self._connection.execute(
                    "SELECT * FROM sessions ORDER BY session_id"
                ).fetchall()
            )
            self._capture_anomaly_provenance = (
                _capture_anomaly_journal_provenance(self._connection)
            )
            self._capture_anomaly_cutoff_id = (
                0
                if self._capture_anomaly_provenance is None
                else _last_capture_anomaly_id(self._connection)
            )
            self._last_observed_at_ms = _last_observed_at_ms(
                self._connection,
                sequence_cutoff=self._replay_cutoff_sequence,
            )
        except Exception:
            if connection is not None:
                connection.close()
            if self._replay_lock_file is not None:
                _release_writer_lock(self._replay_lock_file)
                self._replay_lock_file = None
            raise

    @classmethod
    def for_replay(cls, path: str | Path) -> RecordingReader:
        """Recover and exclusively lease an inactive archive for replay."""

        archive_path = _archive_path(path)
        if not archive_path.is_file():
            raise ArchiveFormatError(
                f"recording archive does not exist: {archive_path}"
            )
        lock_file = _open_writer_lock_file(archive_path)
        connection: sqlite3.Connection | None = None
        try:
            _acquire_writer_lock(lock_file, archive_path)
            connection = _open_connection(archive_path)
            _configure_writer(connection)
            _validate_archive(connection)
            _recover_interrupted_session(connection)
            _checkpoint_wal(connection)
            connection.close()
            connection = None
            return cls(archive_path, _replay_lock_file=lock_file)
        except Exception:
            if connection is not None:
                with suppress(sqlite3.Error):
                    connection.rollback()
                connection.close()
            _release_writer_lock(lock_file)
            raise

    @property
    def target_identity(self) -> str:
        return self._target_identity

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    @property
    def replay_cutoff_sequence(self) -> int:
        """Last event sequence visible to this reader instance."""

        return self._replay_cutoff_sequence

    @property
    def has_capture_anomaly_journal(self) -> bool:
        return self._capture_anomaly_provenance is not None

    @property
    def capture_anomaly_journal_provenance(
        self,
    ) -> RecordingFeatureProvenance | None:
        return self._capture_anomaly_provenance

    @property
    def last_observed_at_ms(self) -> int | None:
        with self._lock:
            self._ensure_open()
            return self._last_observed_at_ms

    def session_durable_end_at_ms(self, session_id: int) -> int | None:
        """Return the latest committed observation in one session snapshot."""

        normalized_session = _positive_int(session_id, "session ID")
        with self._lock:
            self._ensure_open()
            return _last_session_observed_at_ms(
                self._connection,
                normalized_session,
                sequence_cutoff=self._replay_cutoff_sequence,
            )

    def iter_events(
        self,
        *,
        start_at_ms: int | None = None,
        end_at_ms: int | None = None,
        session_id: int | None = None,
        condition_id: str | None = None,
        condition_ids: Iterable[str] | None = None,
        market_slug: str | None = None,
        market_slugs: Iterable[str] | None = None,
        token_id: str | None = None,
        allow_gaps: bool = False,
    ) -> Iterator[RecordedEvent]:
        selection = _selection(
            start_at_ms=start_at_ms,
            end_at_ms=end_at_ms,
            session_id=session_id,
            condition_id=condition_id,
            condition_ids=condition_ids,
            market_slug=market_slug,
            market_slugs=market_slugs,
            token_id=token_id,
        )
        with self._lock:
            self._ensure_open()
            return self._stream_events(selection, allow_gaps=allow_gaps)

    def event_bounds(
        self,
        *,
        start_at_ms: int | None = None,
        end_at_ms: int | None = None,
        session_id: int | None = None,
        condition_id: str | None = None,
        condition_ids: Iterable[str] | None = None,
        market_slug: str | None = None,
        market_slugs: Iterable[str] | None = None,
        token_id: str | None = None,
        allow_gaps: bool = False,
    ) -> RecordingEventBounds | None:
        """Return observed-time and sequence bounds for a validated selection."""

        selection = _selection(
            start_at_ms=start_at_ms,
            end_at_ms=end_at_ms,
            session_id=session_id,
            condition_id=condition_id,
            condition_ids=condition_ids,
            market_slug=market_slug,
            market_slugs=market_slugs,
            token_id=token_id,
        )
        with self._lock:
            self._ensure_open()
            connection = _open_readonly_connection(
                self._path,
                immutable=self._immutable,
            )
            try:
                connection.execute("BEGIN")
                if not allow_gaps:
                    self._reject_known_gaps(connection=connection, **selection)
                query, parameters = _event_query(
                    selection,
                    replay_cutoff_sequence=self._replay_cutoff_sequence,
                    ordered=False,
                )
                boundary_query = (
                    "SELECT sequence, observed_at_ms FROM ("
                    + query
                    + ") AS selected_event WHERE payload_kind != ? "
                    "ORDER BY sequence {} LIMIT 1"
                )
                boundary_parameters = (
                    *parameters,
                    PayloadKind.COVERAGE_GAP.value,
                )
                first = connection.execute(
                    boundary_query.format("ASC"),
                    boundary_parameters,
                ).fetchone()
                if first is None:
                    return None
                last = connection.execute(
                    boundary_query.format("DESC"),
                    boundary_parameters,
                ).fetchone()
                if last is None:
                    raise ArchiveIntegrityError(
                        "recording event bounds are inconsistent"
                    )
                return RecordingEventBounds(
                    first_sequence=_strict_int(
                        first["sequence"],
                        "first event sequence",
                    ),
                    last_sequence=_strict_int(
                        last["sequence"],
                        "last event sequence",
                    ),
                    start_at_ms=_strict_int(
                        first["observed_at_ms"],
                        "first event timestamp",
                    ),
                    end_at_ms=_strict_int(
                        last["observed_at_ms"],
                        "last event timestamp",
                    ),
                )
            finally:
                connection.close()

    def select_session(self, session_id: int | None = None) -> RecordingSession:
        """Select one session, requiring an ID when the archive is ambiguous."""

        with self._lock:
            self._ensure_open()
            if session_id is None:
                if len(self._sessions) != 1:
                    raise ArchiveFormatError(
                        "recording archive requires an explicit session ID"
                    )
                return self._sessions[0]
            normalized_session = _positive_int(session_id, "session ID")
            for session in self._sessions:
                if session.session_id == normalized_session:
                    return session
            raise ArchiveFormatError(
                f"recording session {normalized_session} does not exist"
            )

    def market_at(
        self,
        condition_id: str,
        observed_at_ms: int,
        *,
        allow_gaps: bool = False,
    ) -> MarketMetadataPayload | None:
        normalized_condition = _required_text(condition_id, "condition ID")
        _nonnegative_timestamp(observed_at_ms, "market lookup timestamp")
        with self._lock:
            self._ensure_open()
            if not allow_gaps:
                self._reject_known_gaps(
                    start_at_ms=observed_at_ms,
                    end_at_ms=observed_at_ms,
                    session_id=None,
                    condition_ids=(normalized_condition,),
                    market_slugs=None,
                    token_id=None,
                )
            return self._market_at(
                self._connection,
                normalized_condition,
                observed_at_ms,
            )

    def markets_at(
        self,
        observed_at_ms: int,
        *,
        session_id: int | None = None,
        condition_ids: Iterable[str] | None = None,
        market_slugs: Iterable[str] | None = None,
        allow_gaps: bool = False,
    ) -> tuple[MarketMetadataPayload, ...]:
        """Enumerate latest market revisions visible at one replay time."""

        selection = _selection(
            start_at_ms=observed_at_ms,
            end_at_ms=observed_at_ms,
            session_id=session_id,
            condition_id=None,
            condition_ids=condition_ids,
            market_slug=None,
            market_slugs=market_slugs,
            token_id=None,
        )
        with self._lock:
            self._ensure_open()
            if not allow_gaps:
                self._reject_known_gaps(**selection)
            clauses = [
                "revision.observed_at_ms <= ?",
                "revision.sequence <= ?",
                "revision.sequence = ("
                "SELECT MAX(candidate.sequence) "
                "FROM metadata_revisions AS candidate "
                "WHERE candidate.condition_id = revision.condition_id "
                "AND candidate.observed_at_ms <= ? "
                "AND candidate.sequence <= ?)",
            ]
            parameters: list[object] = [
                observed_at_ms,
                self._replay_cutoff_sequence,
                observed_at_ms,
                self._replay_cutoff_sequence,
            ]
            selected_conditions = selection["condition_ids"]
            if selected_conditions is not None:
                placeholders = ", ".join("?" for _ in selected_conditions)
                clauses.append(f"revision.condition_id IN ({placeholders})")
                parameters.extend(selected_conditions)
            selected_slugs = selection["market_slugs"]
            if selected_slugs is not None:
                placeholders = ", ".join("?" for _ in selected_slugs)
                clauses.append(
                    f"metadata_event.market_slug IN ({placeholders})"
                )
                parameters.extend(selected_slugs)
            selected_session = selection["session_id"]
            if selected_session is not None:
                clauses.append(
                    "EXISTS (SELECT 1 FROM events AS participating_event "
                    "WHERE participating_event.session_id = ? "
                    "AND participating_event.condition_id = revision.condition_id "
                    "AND participating_event.sequence <= ?)"
                )
                parameters.extend(
                    (selected_session, self._replay_cutoff_sequence)
                )
            rows = self._connection.execute(
                "SELECT revision.condition_id, revision.payload_json, "
                "metadata_event.market_slug "
                "FROM metadata_revisions AS revision "
                "JOIN events AS metadata_event "
                "ON metadata_event.sequence = revision.sequence WHERE "
                + " AND ".join(clauses)
                + " ORDER BY revision.condition_id",
                tuple(parameters),
            ).fetchall()
            markets: list[MarketMetadataPayload] = []
            for row in rows:
                payload = _typed_payload(
                    PayloadKind.MARKET_METADATA,
                    row["payload_json"],
                    MarketMetadataPayload,
                )
                if (
                    payload.condition_id != row["condition_id"]
                    or payload.market_slug != row["market_slug"]
                ):
                    raise ArchiveFormatError(
                        "metadata index identity is inconsistent"
                    )
                markets.append(
                    self._market_with_resolution(
                        self._connection,
                        payload,
                        observed_at_ms,
                    )
                )
            return tuple(markets)

    def checkpoint_before(
        self,
        token_id: str,
        observed_at_ms: int,
        *,
        session_id: int | None = None,
        allow_gaps: bool = False,
    ) -> BookCheckpoint | None:
        normalized_token = _required_text(token_id, "token ID")
        _nonnegative_timestamp(observed_at_ms, "checkpoint lookup timestamp")
        normalized_session = (
            None
            if session_id is None
            else _positive_int(session_id, "session ID")
        )
        with self._lock:
            self._ensure_open()
            session_clause = "" if normalized_session is None else "AND session_id = ?"
            parameters: list[object] = [
                normalized_token,
                observed_at_ms,
                self._replay_cutoff_sequence,
            ]
            if normalized_session is not None:
                parameters.append(normalized_session)
            row = self._connection.execute(
                f"""
                SELECT *
                FROM book_checkpoints
                WHERE token_id = ? AND observed_at_ms <= ? AND sequence <= ?
                  {session_clause}
                ORDER BY observed_at_ms DESC, sequence DESC
                LIMIT 1
                """,
                tuple(parameters),
            ).fetchone()
            if row is None:
                return None
            if not allow_gaps:
                self._reject_known_gaps(
                    start_at_ms=int(row["observed_at_ms"]),
                    end_at_ms=observed_at_ms,
                    session_id=normalized_session,
                    condition_ids=(row["condition_id"],),
                    market_slugs=(row["market_slug"],),
                    token_id=normalized_token,
                )
            return self._checkpoint_from_row(row, normalized_token)

    def checkpoint_pair_before(
        self,
        condition_id: str,
        observed_at_ms: int,
        *,
        session_id: int | None = None,
        allow_gaps: bool = False,
    ) -> tuple[BookCheckpoint, BookCheckpoint] | None:
        """Return the newest same-boundary checkpoint for both market tokens."""

        normalized_condition = _required_text(condition_id, "condition ID")
        _nonnegative_timestamp(observed_at_ms, "checkpoint lookup timestamp")
        normalized_session = (
            None
            if session_id is None
            else _positive_int(session_id, "session ID")
        )
        with self._lock:
            self._ensure_open()
            market = self._market_at(
                self._connection,
                normalized_condition,
                observed_at_ms,
            )
            if market is None:
                return None
            token_ids = tuple(outcome.token_id for outcome in market.outcomes)
            session_clause = "" if normalized_session is None else "AND session_id = ?"
            parameters: list[object] = [
                normalized_condition,
                *token_ids,
                observed_at_ms,
                self._replay_cutoff_sequence,
            ]
            if normalized_session is not None:
                parameters.append(normalized_session)
            boundary = self._connection.execute(
                f"""
                SELECT observed_at_ms, sequence, session_id,
                       subscription_generation
                FROM book_checkpoints
                WHERE condition_id = ? AND token_id IN (?, ?)
                  AND observed_at_ms <= ? AND sequence <= ?
                  {session_clause}
                GROUP BY observed_at_ms, sequence, session_id,
                         subscription_generation
                HAVING COUNT(DISTINCT token_id) = 2
                ORDER BY observed_at_ms DESC, sequence DESC
                LIMIT 1
                """,
                tuple(parameters),
            ).fetchone()
            if boundary is None:
                return None
            if not allow_gaps:
                self._reject_known_gaps(
                    start_at_ms=_strict_int(
                        boundary["observed_at_ms"],
                        "checkpoint timestamp",
                    ),
                    end_at_ms=observed_at_ms,
                    session_id=normalized_session,
                    condition_ids=(normalized_condition,),
                    market_slugs=(market.market_slug,),
                    token_id=None,
                )
            rows = self._connection.execute(
                """
                SELECT * FROM book_checkpoints
                WHERE condition_id = ? AND token_id IN (?, ?)
                  AND observed_at_ms = ? AND sequence = ? AND session_id = ?
                  AND subscription_generation = ?
                """,
                (
                    normalized_condition,
                    *token_ids,
                    boundary["observed_at_ms"],
                    boundary["sequence"],
                    boundary["session_id"],
                    boundary["subscription_generation"],
                ),
            ).fetchall()
            rows_by_token = {row["token_id"]: row for row in rows}
            if set(rows_by_token) != set(token_ids):
                raise ArchiveIntegrityError(
                    "common book checkpoint does not contain both market tokens"
                )
            return (
                self._checkpoint_from_row(rows_by_token[token_ids[0]], token_ids[0]),
                self._checkpoint_from_row(rows_by_token[token_ids[1]], token_ids[1]),
            )

    def coverage_gaps(
        self,
        *,
        start_at_ms: int | None = None,
        end_at_ms: int | None = None,
        session_id: int | None = None,
        condition_id: str | None = None,
        condition_ids: Iterable[str] | None = None,
        market_slug: str | None = None,
        market_slugs: Iterable[str] | None = None,
        token_id: str | None = None,
        open_only: bool = False,
    ) -> tuple[CoverageGapRecord, ...]:
        selection = _selection(
            start_at_ms=start_at_ms,
            end_at_ms=end_at_ms,
            session_id=session_id,
            condition_id=condition_id,
            condition_ids=condition_ids,
            market_slug=market_slug,
            market_slugs=market_slugs,
            token_id=token_id,
        )
        with self._lock:
            self._ensure_open()
            return self._coverage_gaps(open_only=open_only, **selection)

    def capture_anomaly_journal_available(self, session_id: int) -> bool:
        selected_session = self.select_session(session_id)
        provenance = self._capture_anomaly_provenance
        return (
            provenance is not None
            and selected_session.session_id
            >= provenance.available_from_session_id
        )

    def capture_anomalies(
        self,
        *,
        start_at_ms: int | None = None,
        end_at_ms: int | None = None,
        session_id: int | None = None,
        condition_id: str | None = None,
        market_slug: str | None = None,
        failure_kind: CaptureFailureKind | str | None = None,
    ) -> tuple[CaptureAnomalyRecord, ...]:
        """Read quarantined diagnostics, never canonical replay events."""

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
            None
            if session_id is None
            else self.select_session(session_id).session_id
        )
        normalized_condition = (
            None
            if condition_id is None
            else _required_text(condition_id, "condition ID")
        )
        normalized_slug = (
            None
            if market_slug is None
            else _required_text(market_slug, "market slug")
        )
        if failure_kind is None:
            normalized_failure = None
        else:
            try:
                normalized_failure = CaptureFailureKind(failure_kind)
            except (TypeError, ValueError) as error:
                raise ValueError("capture anomaly failure kind is invalid") from error
        with self._lock:
            self._ensure_open()
            selected_sessions = _sessions_overlapping(
                self._sessions,
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
                session_id=normalized_session,
            )
            self._require_capture_anomaly_journal(selected_sessions)
            clauses = ["anomaly_id <= ?"]
            parameters: list[object] = [self._capture_anomaly_cutoff_id]
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
            try:
                rows = self._connection.execute(
                    "SELECT * FROM capture_anomalies WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY anomaly_id",
                    tuple(parameters),
                ).fetchall()
            except sqlite3.Error as error:
                raise ArchiveFormatError(
                    "capture anomaly journal is malformed"
                ) from error
            return tuple(_capture_anomaly_from_row(row) for row in rows)

    def sessions(self) -> tuple[RecordingSession, ...]:
        with self._lock:
            self._ensure_open()
            return self._sessions

    def _require_capture_anomaly_journal(
        self,
        selected_sessions: tuple[RecordingSession, ...],
    ) -> None:
        provenance = self._capture_anomaly_provenance
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

    def unresolved_markets(
        self,
        *,
        at_ms: int | None = None,
    ) -> tuple[MarketMetadataPayload, ...]:
        if at_ms is not None:
            _nonnegative_timestamp(at_ms, "unresolved-market timestamp")
        with self._lock:
            self._ensure_open()
            if at_ms is None:
                query = """
                SELECT condition_id, payload_json, sequence
                FROM metadata_revisions AS revision
                WHERE sequence <= ?
                  AND sequence = (
                    SELECT MAX(candidate.sequence)
                    FROM metadata_revisions AS candidate
                    WHERE candidate.condition_id = revision.condition_id
                      AND candidate.sequence <= ?
                )
                ORDER BY condition_id
                """
                parameters: tuple[object, ...] = (
                    self._replay_cutoff_sequence,
                    self._replay_cutoff_sequence,
                )
            else:
                query = """
                SELECT condition_id, payload_json, sequence
                FROM metadata_revisions AS revision
                WHERE observed_at_ms <= ? AND sequence <= ?
                  AND sequence = (
                    SELECT MAX(candidate.sequence)
                    FROM metadata_revisions AS candidate
                    WHERE candidate.condition_id = revision.condition_id
                      AND candidate.observed_at_ms <= ?
                      AND candidate.sequence <= ?
                  )
                ORDER BY condition_id
                """
                parameters = (
                    at_ms,
                    self._replay_cutoff_sequence,
                    at_ms,
                    self._replay_cutoff_sequence,
                )
            rows = self._connection.execute(query, parameters).fetchall()
            unresolved: list[MarketMetadataPayload] = []
            for row in rows:
                payload = _typed_payload(
                    PayloadKind.MARKET_METADATA,
                    row["payload_json"],
                    MarketMetadataPayload,
                )
                if payload.resolved:
                    continue
                resolution_parameters: list[object] = [
                    payload.condition_id,
                    PayloadKind.RESOLUTION.value,
                    self._replay_cutoff_sequence,
                ]
                resolution_time = ""
                if at_ms is not None:
                    resolution_time = " AND observed_at_ms <= ?"
                    resolution_parameters.append(at_ms)
                resolved_row = self._connection.execute(
                    f"""
                    SELECT 1 FROM events
                    WHERE condition_id = ? AND payload_kind = ? AND sequence <= ?
                    {resolution_time}
                    LIMIT 1
                    """,
                    tuple(resolution_parameters),
                ).fetchone()
                if resolved_row is None:
                    unresolved.append(payload)
            return tuple(unresolved)

    def _market_at(
        self,
        connection: sqlite3.Connection,
        condition_id: str,
        observed_at_ms: int,
    ) -> MarketMetadataPayload | None:
        row = connection.execute(
            """
            SELECT payload_json
            FROM metadata_revisions
            WHERE condition_id = ? AND observed_at_ms <= ? AND sequence <= ?
            ORDER BY observed_at_ms DESC, sequence DESC
            LIMIT 1
            """,
            (
                condition_id,
                observed_at_ms,
                self._replay_cutoff_sequence,
            ),
        ).fetchone()
        if row is None:
            return None
        payload = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row["payload_json"],
            MarketMetadataPayload,
        )
        if payload.condition_id != condition_id:
            raise ArchiveFormatError("metadata index identity is inconsistent")
        return self._market_with_resolution(
            connection,
            payload,
            observed_at_ms,
        )

    def _market_with_resolution(
        self,
        connection: sqlite3.Connection,
        payload: MarketMetadataPayload,
        observed_at_ms: int,
    ) -> MarketMetadataPayload:
        resolution_row = connection.execute(
            """
            SELECT * FROM events
            WHERE condition_id = ? AND payload_kind = ?
              AND observed_at_ms <= ? AND sequence <= ?
            ORDER BY observed_at_ms DESC, sequence DESC
            LIMIT 1
            """,
            (
                payload.condition_id,
                PayloadKind.RESOLUTION.value,
                observed_at_ms,
                self._replay_cutoff_sequence,
            ),
        ).fetchone()
        if resolution_row is None:
            return payload
        resolution_event = _event_from_row(resolution_row)
        if not isinstance(resolution_event.payload, ResolutionPayload):
            raise ArchiveFormatError("resolution index contains a wrong payload")
        _validate_payload_market_identity(resolution_event, payload)
        return replace(
            payload,
            resolution_status=(
                payload.resolution_status if payload.resolved else "resolved"
            ),
            resolution_source=(
                payload.resolution_source or resolution_event.payload.source
            ),
            resolved=True,
            winning_token_id=resolution_event.payload.winning_token_id,
            winning_outcome=resolution_event.payload.winning_outcome,
        )

    def _checkpoint_from_row(
        self,
        row: sqlite3.Row,
        token_id: str,
    ) -> BookCheckpoint:
        sequence = _strict_int(row["sequence"], "checkpoint sequence")
        if sequence > self._replay_cutoff_sequence:
            raise ArchiveIntegrityError("book checkpoint exceeds the replay cutoff")
        book = _typed_payload(
            PayloadKind.BOOK_BASELINE,
            row["payload_json"],
            BookBaselinePayload,
        )
        metadata_row = self._connection.execute(
            """
            SELECT payload_json FROM metadata_revisions
            WHERE condition_id = ? AND sequence <= ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (row["condition_id"], sequence),
        ).fetchone()
        if metadata_row is None:
            raise ArchiveIntegrityError(
                "book checkpoint has no preceding market metadata"
            )
        market = _typed_payload(
            PayloadKind.MARKET_METADATA,
            metadata_row["payload_json"],
            MarketMetadataPayload,
        )
        if (
            row["condition_id"] != market.condition_id
            or row["market_slug"] != market.market_slug
            or token_id not in {outcome.token_id for outcome in market.outcomes}
            or book.token_id != token_id
        ):
            raise ArchiveIntegrityError(
                "book checkpoint identity does not match market metadata"
            )
        try:
            return BookCheckpoint(
                sequence=sequence,
                session_id=_strict_int(row["session_id"], "checkpoint session"),
                subscription_generation=_strict_int(
                    row["subscription_generation"],
                    "checkpoint generation",
                ),
                observed_at_ms=_strict_int(
                    row["observed_at_ms"],
                    "checkpoint timestamp",
                ),
                identity=MarketIdentity(
                    condition_id=row["condition_id"],
                    market_slug=row["market_slug"],
                    token_id=token_id,
                ),
                book=book,
            )
        except ValueError as error:
            raise ArchiveFormatError("book checkpoint is malformed") from error

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._connection.close()
            finally:
                if self._replay_lock_file is not None:
                    _release_writer_lock(self._replay_lock_file)
                    self._replay_lock_file = None
                self._closed = True

    def __enter__(self) -> RecordingReader:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _stream_events(
        self,
        selection: dict[str, object],
        *,
        allow_gaps: bool,
    ) -> Iterator[RecordedEvent]:
        connection = _open_readonly_connection(
            self._path,
            immutable=self._immutable,
        )
        try:
            connection.execute("BEGIN")
            if not allow_gaps:
                self._reject_known_gaps(connection=connection, **selection)
            query, parameters = _event_query(
                selection,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
            )
            cursor = connection.execute(query, parameters)
        except BaseException:
            connection.close()
            raise

        def iterate() -> Iterator[RecordedEvent]:
            verified_metadata: dict[str, MarketMetadataPayload] = {}
            verified_baselines: set[tuple[int, int, str]] = set()
            try:
                for row in cursor:
                    event = _event_from_row(row)
                    if (
                        isinstance(event.payload, CoverageGapPayload)
                        and not _gap_affects(
                            event.identity,
                            event.payload,
                            condition_ids=selection["condition_ids"],
                            market_slugs=selection["market_slugs"],
                            token_id=selection["token_id"],
                        )
                    ):
                        continue
                    _validate_stored_event_dependencies(
                        connection,
                        event,
                        verified_metadata,
                        verified_baselines,
                    )
                    yield event
            finally:
                connection.close()

        return iterate()

    def _coverage_gaps(
        self,
        *,
        start_at_ms: int | None,
        end_at_ms: int | None,
        session_id: int | None,
        condition_ids: tuple[str, ...] | None,
        market_slugs: tuple[str, ...] | None,
        token_id: str | None,
        open_only: bool,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[CoverageGapRecord, ...]:
        clauses: list[str] = ["event_sequence <= ?"]
        parameters: list[object] = [self._replay_cutoff_sequence]
        if start_at_ms is not None:
            clauses.append("(ended_at_ms IS NULL OR ended_at_ms > ?)")
            parameters.append(start_at_ms)
        if end_at_ms is not None:
            clauses.append("started_at_ms <= ?")
            parameters.append(end_at_ms)
        if session_id is not None:
            clauses.append("session_id = ?")
            parameters.append(session_id)
        if open_only:
            clauses.append("ended_at_ms IS NULL")
        where = "" if not clauses else "WHERE " + " AND ".join(clauses)
        selected_connection = self._connection if connection is None else connection
        rows = selected_connection.execute(
            f"SELECT * FROM coverage_gaps {where} ORDER BY started_at_ms, gap_id",
            tuple(parameters),
        ).fetchall()
        result: list[CoverageGapRecord] = []
        for row in rows:
            payload = _typed_payload(
                PayloadKind.COVERAGE_GAP,
                row["payload_json"],
                CoverageGapPayload,
            )
            identity = _identity_from_row(row)
            if not _gap_affects(
                identity,
                payload,
                condition_ids=condition_ids,
                market_slugs=market_slugs,
                token_id=token_id,
            ):
                continue
            if (
                payload.started_at_ms != row["started_at_ms"]
                or payload.ended_at_ms != row["ended_at_ms"]
                or payload.reason != row["reason"]
            ):
                raise ArchiveFormatError("coverage gap index is inconsistent")
            try:
                result.append(
                    CoverageGapRecord(
                        gap_id=_strict_int(row["gap_id"], "coverage gap ID"),
                        event_sequence=_strict_int(
                            row["event_sequence"],
                            "coverage gap sequence",
                        ),
                        session_id=_strict_int(
                            row["session_id"],
                            "coverage gap session",
                        ),
                        subscription_generation=_strict_int(
                            row["subscription_generation"],
                            "coverage gap generation",
                        ),
                        observed_at_ms=_strict_int(
                            row["observed_at_ms"],
                            "coverage gap observation",
                        ),
                        identity=identity,
                        gap=payload,
                    )
                )
            except ValueError as error:
                raise ArchiveFormatError("coverage gap record is malformed") from error
        return tuple(result)

    def _reject_known_gaps(
        self,
        *,
        start_at_ms: int | None,
        end_at_ms: int | None,
        session_id: int | None,
        condition_ids: tuple[str, ...] | None,
        market_slugs: tuple[str, ...] | None,
        token_id: str | None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        gaps = self._coverage_gaps(
            start_at_ms=start_at_ms,
            end_at_ms=end_at_ms,
            session_id=session_id,
            condition_ids=condition_ids,
            market_slugs=market_slugs,
            token_id=token_id,
            open_only=False,
            connection=connection,
        )
        if gaps:
            raise ArchiveCoverageError(
                _coverage_gap_error_message(tuple(gap.gap_id for gap in gaps))
            )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArchiveClosedError("recording reader is closed")


def _coverage_gap_error_message(gap_ids: tuple[int, ...]) -> str:
    prefix = "selected recording interval crosses known coverage gaps"
    gap_ids = tuple(sorted(gap_ids))
    if len(gap_ids) <= 20:
        return f"{prefix}: {', '.join(str(gap_id) for gap_id in gap_ids)}"

    ranges: list[tuple[int, int]] = []
    range_start = range_end = gap_ids[0]
    for gap_id in gap_ids[1:]:
        if gap_id == range_end + 1:
            range_end = gap_id
            continue
        ranges.append((range_start, range_end))
        range_start = range_end = gap_id
    ranges.append((range_start, range_end))

    displayed_ranges = ranges[:8]
    summary = ", ".join(
        str(start) if start == end else f"{start}-{end}"
        for start, end in displayed_ranges
    )
    if len(ranges) > len(displayed_ranges):
        summary = f"{summary}, ..."
    return f"{prefix}: {len(gap_ids):,} gaps (IDs {summary})"


def _initialize_schema(
    connection: sqlite3.Connection,
    *,
    target_identity: str,
    created_at_ms: int,
) -> None:
    connection.executescript(
        f"""
        BEGIN IMMEDIATE;
        PRAGMA application_id = {SQLITE_APPLICATION_ID};
        PRAGMA user_version = {SCHEMA_VERSION};

        CREATE TABLE archive_meta (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            schema_version INTEGER NOT NULL,
            target_identity TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
        ) STRICT;

        CREATE TABLE sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
            ended_at_ms INTEGER CHECK (
                ended_at_ms IS NULL OR ended_at_ms >= started_at_ms
            ),
            clean_close INTEGER NOT NULL DEFAULT 0 CHECK (clean_close IN (0, 1)),
            integrity_status TEXT NOT NULL CHECK (
                integrity_status IN ('active', 'complete', 'incomplete', 'failed')
            ),
            recorder_version TEXT NOT NULL,
            sdk_version TEXT NOT NULL,
            failure_reason TEXT
        ) STRICT;

        CREATE TABLE events (
            sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            source_timestamp_ms INTEGER CHECK (
                source_timestamp_ms IS NULL OR source_timestamp_ms >= 0
            ),
            condition_id TEXT,
            market_slug TEXT,
            token_id TEXT,
            payload_kind TEXT NOT NULL CHECK (
                payload_kind IN (
                    'market_metadata', 'book_baseline', 'book_delta',
                    'public_trade', 'tick_size_change', 'resolution', 'coverage_gap'
                )
            ),
            payload_json TEXT NOT NULL
        ) STRICT;

        CREATE TABLE event_tokens (
            sequence INTEGER NOT NULL REFERENCES events(sequence) ON DELETE CASCADE,
            token_id TEXT NOT NULL,
            PRIMARY KEY (sequence, token_id)
        ) WITHOUT ROWID;

        CREATE TABLE metadata_revisions (
            condition_id TEXT NOT NULL,
            sequence INTEGER NOT NULL UNIQUE REFERENCES events(sequence),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            payload_json TEXT NOT NULL,
            PRIMARY KEY (condition_id, sequence)
        ) WITHOUT ROWID;

        CREATE TABLE book_checkpoints (
            token_id TEXT NOT NULL,
            sequence INTEGER NOT NULL REFERENCES events(sequence),
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            condition_id TEXT NOT NULL,
            market_slug TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (token_id, observed_at_ms, sequence)
        ) WITHOUT ROWID;

        CREATE TABLE coverage_gaps (
            gap_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_sequence INTEGER NOT NULL UNIQUE REFERENCES events(sequence),
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            condition_id TEXT,
            market_slug TEXT,
            started_at_ms INTEGER NOT NULL CHECK (started_at_ms >= 0),
            ended_at_ms INTEGER CHECK (
                ended_at_ms IS NULL OR ended_at_ms >= started_at_ms
            ),
            reason TEXT NOT NULL,
            payload_json TEXT NOT NULL
        ) STRICT;

        CREATE INDEX events_observed_idx ON events(observed_at_ms, sequence);
        CREATE INDEX events_condition_idx
            ON events(condition_id, observed_at_ms, sequence);
        CREATE INDEX events_slug_idx ON events(market_slug, observed_at_ms, sequence);
        CREATE INDEX event_tokens_token_idx ON event_tokens(token_id, sequence);
        CREATE INDEX metadata_time_idx
            ON metadata_revisions(condition_id, observed_at_ms, sequence);
        CREATE INDEX checkpoints_time_idx
            ON book_checkpoints(token_id, observed_at_ms, sequence);
        CREATE INDEX coverage_gaps_time_idx
            ON coverage_gaps(started_at_ms, ended_at_ms);

        INSERT INTO archive_meta (
            singleton, schema_version, target_identity, created_at_ms
        ) VALUES (1, {SCHEMA_VERSION}, {sql_quote(target_identity)}, {created_at_ms});
        COMMIT;
        """
    )


def _ensure_capture_anomaly_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS recording_features (
            feature_name TEXT PRIMARY KEY,
            available_from_session_id INTEGER NOT NULL
                REFERENCES sessions(session_id),
            enabled_at_ms INTEGER NOT NULL CHECK (enabled_at_ms >= 0),
            recorder_version TEXT NOT NULL
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS capture_anomalies (
            anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(session_id),
            subscription_generation INTEGER NOT NULL CHECK (
                subscription_generation >= 0
            ),
            observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
            condition_id TEXT,
            market_slug TEXT,
            token_id TEXT,
            failure_kind TEXT NOT NULL,
            payload_json TEXT NOT NULL
        ) STRICT
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS capture_anomalies_session_time_idx
        ON capture_anomalies(session_id, observed_at_ms, anomaly_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS capture_anomalies_condition_idx
        ON capture_anomalies(condition_id, observed_at_ms, anomaly_id)
        """
    )


def _enable_capture_anomaly_journal(
    connection: sqlite3.Connection,
    *,
    available_from_session_id: int,
    enabled_at_ms: int,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO recording_features (
            feature_name, available_from_session_id, enabled_at_ms,
            recorder_version
        ) VALUES (?, ?, ?, ?)
        """,
        (
            CAPTURE_ANOMALY_JOURNAL_FEATURE,
            available_from_session_id,
            enabled_at_ms,
            _distribution_version(RECORDER_DISTRIBUTION),
        ),
    )


def _capture_anomaly_journal_provenance(
    connection: sqlite3.Connection,
) -> RecordingFeatureProvenance | None:
    try:
        if not _table_exists(connection, "recording_features"):
            return None
        row = connection.execute(
            """
            SELECT feature_name, available_from_session_id, enabled_at_ms,
                   recorder_version
            FROM recording_features
            WHERE feature_name = ?
            """,
            (CAPTURE_ANOMALY_JOURNAL_FEATURE,),
        ).fetchone()
        if row is None:
            return None
        if not _table_exists(connection, "capture_anomalies"):
            raise ArchiveFormatError(
                "capture anomaly journal feature table is missing"
            )
        provenance = RecordingFeatureProvenance(
            feature_name=_required_text(row["feature_name"], "feature name"),
            available_from_session_id=_positive_int(
                row["available_from_session_id"],
                "feature activation session ID",
            ),
            enabled_at_ms=_nonnegative_timestamp(
                row["enabled_at_ms"],
                "feature activation timestamp",
            ),
            recorder_version=_required_text(
                row["recorder_version"],
                "feature recorder version",
            ),
        )
        activation_session = connection.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?",
            (provenance.available_from_session_id,),
        ).fetchone()
        if activation_session is None:
            raise ArchiveFormatError(
                "capture anomaly journal activation session does not exist"
            )
        return provenance
    except ArchiveFormatError:
        raise
    except (IndexError, sqlite3.Error, TypeError, ValueError) as error:
        raise ArchiveFormatError(
            "capture anomaly journal provenance is malformed"
        ) from error


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _insert_session(connection: sqlite3.Connection, started_at_ms: int) -> int:
    cursor = connection.execute(
        """
        INSERT INTO sessions (
            started_at_ms, integrity_status, recorder_version, sdk_version
        ) VALUES (?, ?, ?, ?)
        """,
        (
            started_at_ms,
            SessionIntegrityStatus.ACTIVE.value,
            _distribution_version(RECORDER_DISTRIBUTION),
            _distribution_version(SDK_DISTRIBUTION),
        ),
    )
    return int(cursor.lastrowid)


def _validate_archive(connection: sqlite3.Connection) -> str:
    try:
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if application_id != SQLITE_APPLICATION_ID or schema_version != SCHEMA_VERSION:
            raise ArchiveFormatError(
                f"unsupported recording archive schema version {schema_version}"
            )
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ArchiveFormatError("recording archive failed SQLite integrity check")
        row = connection.execute(
            """
            SELECT schema_version, target_identity
            FROM archive_meta
            WHERE singleton = 1
            """
        ).fetchone()
        if row is None or row["schema_version"] != SCHEMA_VERSION:
            raise ArchiveFormatError("recording archive metadata is malformed")
        return _required_text(row["target_identity"], "stored target identity")
    except ArchiveFormatError:
        raise
    except (IndexError, sqlite3.Error, TypeError, ValueError) as error:
        raise ArchiveFormatError("recording archive format is malformed") from error


def _latest_session(connection: sqlite3.Connection) -> RecordingSession | None:
    row = connection.execute(
        "SELECT * FROM sessions ORDER BY session_id DESC LIMIT 1"
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
            """
            UPDATE sessions
            SET ended_at_ms = ?, clean_close = 0, integrity_status = ?,
                failure_reason = ?
            WHERE session_id = ?
            """,
            (
                ended_at_ms,
                SessionIntegrityStatus.INCOMPLETE.value,
                INTERRUPTED_SESSION_REASON,
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


def _latest_metadata(
    connection: sqlite3.Connection,
) -> dict[str, MarketMetadataPayload]:
    rows = connection.execute(
        """
        SELECT revision.condition_id, revision.payload_json
        FROM metadata_revisions AS revision
        WHERE revision.sequence = (
            SELECT MAX(candidate.sequence)
            FROM metadata_revisions AS candidate
            WHERE candidate.condition_id = revision.condition_id
        )
        """
    ).fetchall()
    result: dict[str, MarketMetadataPayload] = {}
    for row in rows:
        payload = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row["payload_json"],
            MarketMetadataPayload,
        )
        if payload.condition_id != row["condition_id"]:
            raise ArchiveFormatError("metadata revision identity is inconsistent")
        result[payload.condition_id] = payload
    return result


def _event_from_row(row: sqlite3.Row) -> RecordedEvent:
    try:
        payload = payload_from_json(row["payload_kind"], row["payload_json"])
        return RecordedEvent(
            sequence=_strict_int(row["sequence"], "event sequence"),
            session_id=_strict_int(row["session_id"], "event session"),
            subscription_generation=_strict_int(
                row["subscription_generation"],
                "event generation",
            ),
            observed_at_ms=_strict_int(row["observed_at_ms"], "event observation"),
            source_timestamp_ms=_optional_strict_int(
                row["source_timestamp_ms"],
                "event source timestamp",
            ),
            identity=_identity_from_row(row),
            payload=payload,
        )
    except (TypeError, ValueError) as error:
        sequence = row["sequence"] if "sequence" in row.keys() else "unknown"
        raise ArchiveFormatError(
            f"recording event {sequence} is malformed"
        ) from error


def _capture_anomaly_from_row(row: sqlite3.Row) -> CaptureAnomalyRecord:
    try:
        anomaly = capture_anomaly_from_json(row["payload_json"])
        failure_kind = CaptureFailureKind(row["failure_kind"])
        if anomaly.failure_kind is not failure_kind:
            raise ValueError("capture anomaly failure kind index is inconsistent")
        identity = _identity_from_row(row)
        if identity is None:
            raise ValueError("capture anomaly has no market identity")
        if not anomaly.matches_index_identity(identity):
            raise ValueError(
                "capture anomaly identity index is inconsistent"
            )
        return CaptureAnomalyRecord(
            anomaly_id=_strict_int(row["anomaly_id"], "capture anomaly ID"),
            session_id=_strict_int(row["session_id"], "capture anomaly session"),
            subscription_generation=_strict_int(
                row["subscription_generation"],
                "capture anomaly generation",
            ),
            observed_at_ms=_strict_int(
                row["observed_at_ms"],
                "capture anomaly observation",
            ),
            identity=identity,
            anomaly=anomaly,
        )
    except (IndexError, TypeError, ValueError) as error:
        anomaly_id = row["anomaly_id"] if "anomaly_id" in row.keys() else "unknown"
        raise ArchiveFormatError(
            f"capture anomaly {anomaly_id} is malformed"
        ) from error


def _identity_from_row(row: sqlite3.Row) -> MarketIdentity | None:
    condition_id = row["condition_id"]
    market_slug = row["market_slug"]
    token_id = row["token_id"] if "token_id" in row.keys() else None
    if condition_id is None and market_slug is None and token_id is None:
        return None
    return MarketIdentity(
        condition_id=condition_id,
        market_slug=market_slug,
        token_id=token_id,
    )


def _typed_payload(
    kind: PayloadKind,
    raw_json: str,
    expected_type: type,
):
    try:
        payload = payload_from_json(kind, raw_json)
    except ValueError as error:
        raise ArchiveFormatError(f"stored {kind.value} payload is malformed") from error
    if not isinstance(payload, expected_type):
        raise ArchiveFormatError(f"stored {kind.value} payload has a wrong type")
    return payload


def _validate_event_dependencies(
    event: RecordedEvent,
    metadata: dict[str, MarketMetadataPayload],
    baselines: set[tuple[int, str]],
) -> None:
    if isinstance(event.payload, CoverageGapPayload):
        return
    identity = event.identity
    if identity is None or identity.condition_id is None:
        raise ArchiveIntegrityError(
            "market event requires a resolved condition identity"
        )
    if isinstance(event.payload, MarketMetadataPayload):
        _validate_metadata_revision(event.payload, metadata)
        return
    if identity.condition_id not in metadata:
        raise ArchiveIntegrityError(
            "market metadata must be committed before dependent events"
        )
    _validate_payload_market_identity(event, metadata[identity.condition_id])
    if isinstance(event.payload, BookDeltaPayload):
        missing = [
            token_id
            for token_id in event_token_ids(event.payload)
            if (event.subscription_generation, token_id) not in baselines
        ]
        if missing:
            raise ArchiveIntegrityError(
                "book delta is missing a baseline in its subscription generation: "
                + ", ".join(missing)
            )


def _validate_metadata_revision(
    revision: MarketMetadataPayload,
    metadata: dict[str, MarketMetadataPayload],
) -> None:
    token_ids = {outcome.token_id for outcome in revision.outcomes}
    for condition_id, existing in metadata.items():
        existing_token_ids = {outcome.token_id for outcome in existing.outcomes}
        if condition_id != revision.condition_id and token_ids & existing_token_ids:
            raise ArchiveIntegrityError("market token ID maps to multiple conditions")
    previous = metadata.get(revision.condition_id)
    if previous is None:
        return
    if (
        previous.market_id != revision.market_id
        or previous.market_slug != revision.market_slug
        or tuple(
            (outcome.label, outcome.token_id) for outcome in previous.outcomes
        )
        != tuple((outcome.label, outcome.token_id) for outcome in revision.outcomes)
    ):
        raise ArchiveIntegrityError(
            "market metadata revision changed immutable identity"
        )


def _validate_payload_market_identity(
    event: RecordedEvent,
    market: MarketMetadataPayload,
) -> None:
    identity = event.identity
    if identity is None:
        raise ArchiveIntegrityError("market event has no identity")
    if (
        identity.condition_id != market.condition_id
        or identity.market_slug != market.market_slug
    ):
        raise ArchiveIntegrityError("event identity does not match market metadata")
    market_tokens = {outcome.token_id for outcome in market.outcomes}
    payload_tokens = set(event_token_ids(event.payload))
    if not payload_tokens <= market_tokens:
        raise ArchiveIntegrityError(
            "event token identity does not match market metadata"
        )
    if not isinstance(event.payload, ResolutionPayload):
        return
    if payload_tokens != market_tokens:
        raise ArchiveIntegrityError(
            "resolution token pair does not match market metadata"
        )
    outcome_by_token = {
        outcome.token_id: outcome.label for outcome in market.outcomes
    }
    expected_outcome = outcome_by_token[event.payload.winning_token_id]
    if event.payload.winning_outcome != expected_outcome:
        raise ArchiveIntegrityError("resolution outcome does not match market metadata")


def _invalidate_gap_baselines(
    gap: CoverageGapPayload,
    metadata: dict[str, MarketMetadataPayload],
    baselines: set[tuple[int, str]],
    *,
    identity: MarketIdentity | None,
) -> None:
    affected_tokens = set(gap.affected_token_ids)
    affected_conditions = set(gap.affected_condition_ids)
    affected_slugs = set(gap.affected_market_slugs)
    has_payload_scope = bool(
        affected_tokens or affected_conditions or affected_slugs
    )
    if not has_payload_scope and identity is not None:
        if identity.token_id is not None:
            affected_tokens.add(identity.token_id)
        else:
            if identity.condition_id is not None:
                affected_conditions.add(identity.condition_id)
            if identity.market_slug is not None:
                affected_slugs.add(identity.market_slug)
    for market in metadata.values():
        if (
            market.condition_id in affected_conditions
            or market.market_slug in affected_slugs
        ):
            affected_tokens.update(outcome.token_id for outcome in market.outcomes)
    if not affected_tokens and not affected_conditions and not affected_slugs:
        baselines.clear()
        return
    baselines.difference_update(
        {key for key in baselines if key[1] in affected_tokens}
    )


def _validate_stored_event_dependencies(
    connection: sqlite3.Connection,
    event: RecordedEvent,
    verified_metadata: dict[str, MarketMetadataPayload],
    verified_baselines: set[tuple[int, int, str]],
) -> None:
    if isinstance(event.payload, MarketMetadataPayload):
        _validate_metadata_revision(event.payload, verified_metadata)
        verified_metadata[event.payload.condition_id] = event.payload
        return
    if isinstance(event.payload, CoverageGapPayload):
        _invalidate_stored_gap_baselines(
            event,
            verified_metadata,
            verified_baselines,
        )
        return
    identity = event.identity
    if identity is None or identity.condition_id is None:
        raise ArchiveFormatError("stored market event lacks condition identity")
    if identity.condition_id not in verified_metadata:
        row = connection.execute(
            """
            SELECT payload_json FROM metadata_revisions
            WHERE condition_id = ? AND sequence < ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (identity.condition_id, event.sequence),
        ).fetchone()
        if row is None:
            raise ArchiveIntegrityError(
                f"event {event.sequence} has no preceding market metadata"
            )
        market = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row["payload_json"],
            MarketMetadataPayload,
        )
        if market.condition_id != identity.condition_id:
            raise ArchiveFormatError("metadata revision identity is inconsistent")
        verified_metadata[identity.condition_id] = market
    _validate_payload_market_identity(
        event,
        verified_metadata[identity.condition_id],
    )
    if isinstance(event.payload, BookBaselinePayload):
        verified_baselines.add(
            (
                event.session_id,
                event.subscription_generation,
                event.payload.token_id,
            )
        )
        return
    if not isinstance(event.payload, BookDeltaPayload):
        return
    for token_id in event_token_ids(event.payload):
        baseline_key = (
            event.session_id,
            event.subscription_generation,
            token_id,
        )
        if baseline_key in verified_baselines:
            continue
        row = connection.execute(
            """
            SELECT event.sequence
            FROM events AS event
            JOIN event_tokens AS token ON token.sequence = event.sequence
            WHERE event.payload_kind = ?
              AND event.subscription_generation = ?
              AND event.session_id = ?
              AND token.token_id = ?
              AND event.sequence < ?
            ORDER BY event.sequence DESC
            LIMIT 1
            """,
            (
                PayloadKind.BOOK_BASELINE.value,
                event.subscription_generation,
                event.session_id,
                token_id,
                event.sequence,
            ),
        ).fetchone()
        if row is None or _has_affecting_gap_after_baseline(
            connection,
            baseline_sequence=_strict_int(
                row["sequence"],
                "baseline sequence",
            ),
            event=event,
            token_id=token_id,
        ):
            raise ArchiveIntegrityError(
                f"book delta event {event.sequence} has no preceding baseline"
            )
        verified_baselines.add(baseline_key)


def _has_affecting_gap_after_baseline(
    connection: sqlite3.Connection,
    *,
    baseline_sequence: int,
    event: RecordedEvent,
    token_id: str,
) -> bool:
    identity = event.identity
    if identity is None:
        raise AssertionError("book delta has no market identity")
    rows = connection.execute(
        """
        SELECT * FROM events
        WHERE payload_kind = ? AND sequence > ? AND sequence < ?
        ORDER BY sequence
        """,
        (
            PayloadKind.COVERAGE_GAP.value,
            baseline_sequence,
            event.sequence,
        ),
    )
    for row in rows:
        gap_event = _event_from_row(row)
        if not isinstance(gap_event.payload, CoverageGapPayload):
            raise ArchiveFormatError("coverage-gap index contains a wrong payload")
        if _gap_affects(
            gap_event.identity,
            gap_event.payload,
            condition_ids=(identity.condition_id,),
            market_slugs=(identity.market_slug,),
            token_id=token_id,
        ):
            return True
    return False


def _invalidate_stored_gap_baselines(
    event: RecordedEvent,
    metadata: dict[str, MarketMetadataPayload],
    baselines: set[tuple[int, int, str]],
) -> None:
    gap = event.payload
    if not isinstance(gap, CoverageGapPayload):
        raise AssertionError("baseline invalidation requires a coverage gap")
    identity = event.identity
    affected_tokens = set(gap.affected_token_ids)
    if not affected_tokens and identity is not None and identity.token_id is not None:
        affected_tokens.add(identity.token_id)
    if affected_tokens:
        baselines.difference_update(
            {key for key in baselines if key[2] in affected_tokens}
        )
        return

    affected_conditions = set(gap.affected_condition_ids)
    affected_slugs = set(gap.affected_market_slugs)
    if identity is not None:
        if not affected_conditions and identity.condition_id is not None:
            affected_conditions.add(identity.condition_id)
        if not affected_slugs and identity.market_slug is not None:
            affected_slugs.add(identity.market_slug)
    if not affected_conditions and not affected_slugs:
        baselines.clear()
        return
    for market in metadata.values():
        if (
            market.condition_id in affected_conditions
            or market.market_slug in affected_slugs
        ):
            affected_tokens.update(
                outcome.token_id for outcome in market.outcomes
            )
    baselines.difference_update(
        {key for key in baselines if key[2] in affected_tokens}
    )


def _selection(
    *,
    start_at_ms: int | None,
    end_at_ms: int | None,
    session_id: int | None,
    condition_id: str | None,
    condition_ids: Iterable[str] | None,
    market_slug: str | None,
    market_slugs: Iterable[str] | None,
    token_id: str | None,
) -> dict[str, object]:
    if start_at_ms is not None:
        _nonnegative_timestamp(start_at_ms, "selection start")
    if end_at_ms is not None:
        _nonnegative_timestamp(end_at_ms, "selection end")
    if start_at_ms is not None and end_at_ms is not None and end_at_ms < start_at_ms:
        raise ValueError("recording selection cannot end before it starts")
    return {
        "start_at_ms": start_at_ms,
        "end_at_ms": end_at_ms,
        "session_id": (
            None if session_id is None else _positive_int(session_id, "session ID")
        ),
        "condition_ids": _text_selection(
            singular=condition_id,
            plural=condition_ids,
            singular_name="condition ID",
            plural_name="condition IDs",
        ),
        "market_slugs": _text_selection(
            singular=market_slug,
            plural=market_slugs,
            singular_name="market slug",
            plural_name="market slugs",
        ),
        "token_id": None if token_id is None else _required_text(token_id, "token ID"),
    }


def _text_selection(
    *,
    singular: str | None,
    plural: Iterable[str] | None,
    singular_name: str,
    plural_name: str,
) -> tuple[str, ...] | None:
    if singular is not None and plural is not None:
        raise ValueError(f"use either {singular_name} or {plural_name}, not both")
    if singular is not None:
        return (_required_text(singular, singular_name),)
    if plural is None:
        return None
    if isinstance(plural, str):
        raise ValueError(f"{plural_name} must be an iterable of strings")
    normalized = tuple(
        sorted({_required_text(value, singular_name) for value in plural})
    )
    if not normalized:
        raise ValueError(f"{plural_name} must not be empty")
    return normalized


def _event_query(
    selection: dict[str, object],
    *,
    replay_cutoff_sequence: int,
    ordered: bool = True,
) -> tuple[str, tuple[object, ...]]:
    clauses: list[str] = ["event.sequence <= ?"]
    parameters: list[object] = [replay_cutoff_sequence]
    start_at_ms = selection["start_at_ms"]
    end_at_ms = selection["end_at_ms"]
    session_id = selection["session_id"]
    condition_ids = selection["condition_ids"]
    market_slugs = selection["market_slugs"]
    token_id = selection["token_id"]
    if start_at_ms is not None:
        clauses.append("event.observed_at_ms >= ?")
        parameters.append(start_at_ms)
    if end_at_ms is not None:
        clauses.append("event.observed_at_ms <= ?")
        parameters.append(end_at_ms)
    if session_id is not None:
        clauses.append("event.session_id = ?")
        parameters.append(session_id)
    if condition_ids is not None:
        placeholders = ", ".join("?" for _ in condition_ids)
        clauses.append(
            f"(event.condition_id IN ({placeholders}) OR event.payload_kind = ?)"
        )
        parameters.extend((*condition_ids, PayloadKind.COVERAGE_GAP.value))
    if market_slugs is not None:
        placeholders = ", ".join("?" for _ in market_slugs)
        clauses.append(
            f"(event.market_slug IN ({placeholders}) OR event.payload_kind = ?)"
        )
        parameters.extend((*market_slugs, PayloadKind.COVERAGE_GAP.value))
    if token_id is not None:
        clauses.append(
            """
            (EXISTS (
                SELECT 1 FROM event_tokens AS selected_token
                WHERE selected_token.sequence = event.sequence
                  AND selected_token.token_id = ?
            ) OR event.payload_kind = ?)
            """
        )
        parameters.extend((token_id, PayloadKind.COVERAGE_GAP.value))
    where = "" if not clauses else "WHERE " + " AND ".join(clauses)
    order_by = " ORDER BY event.sequence" if ordered else ""
    return (
        f"SELECT event.* FROM events AS event {where}{order_by}",
        tuple(parameters),
    )


def _gap_affects(
    identity: MarketIdentity | None,
    gap: CoverageGapPayload,
    *,
    condition_ids: tuple[str, ...] | None,
    market_slugs: tuple[str, ...] | None,
    token_id: str | None,
) -> bool:
    has_scope = bool(
        gap.affected_condition_ids
        or gap.affected_market_slugs
        or gap.affected_token_ids
        or identity is not None
    )
    if not has_scope:
        return True
    return all(
        _selected_scope_matches(
            selected,
            affected,
            identity_value,
        )
        for selected, affected, identity_value in (
            (
                condition_ids,
                gap.affected_condition_ids,
                None if identity is None else identity.condition_id,
            ),
            (
                market_slugs,
                gap.affected_market_slugs,
                None if identity is None else identity.market_slug,
            ),
            (
                None if token_id is None else (token_id,),
                gap.affected_token_ids,
                None if identity is None else identity.token_id,
            ),
        )
    )


def _selected_scope_matches(
    selected: tuple[str, ...] | None,
    affected: tuple[str, ...],
    identity_value: str | None,
) -> bool:
    if selected is None:
        return True
    if affected:
        return not set(selected).isdisjoint(affected)
    return identity_value is None or identity_value in selected


def _archive_path(path: str | Path) -> Path:
    if isinstance(path, Path):
        archive_path = path
    elif isinstance(path, str) and path.strip():
        archive_path = Path(path)
    else:
        raise ValueError("recording archive path must not be empty")
    return archive_path.expanduser().resolve()


def _open_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path,
        timeout=0,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _open_readonly_connection(
    path: Path,
    *,
    immutable: bool = False,
) -> sqlite3.Connection:
    immutable_parameter = "&immutable=1" if immutable else ""
    uri = f"file:{quote(str(path))}?mode=ro{immutable_parameter}"
    try:
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except sqlite3.Error as error:
        raise ArchiveFormatError("could not open recording archive") from error


def _configure_writer(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 0")
    journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(journal_mode).casefold() != "wal":
        raise RecordingArchiveError("recording archive could not enable WAL mode")
    connection.execute("PRAGMA synchronous = FULL")


def _checkpoint_wal(connection: sqlite3.Connection) -> None:
    try:
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except sqlite3.Error as error:
        raise RecordingArchiveError(
            "recording archive WAL could not be checkpointed"
        ) from error
    if result is None or int(result[0]) != 0:
        raise ArchiveLockedError(
            "recording archive has an active reader and cannot be leased for replay"
        )


def _acquire_writer_lock(lock_file: BinaryIO, path: Path) -> None:
    try:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except (BlockingIOError, OSError) as error:
        lock_file.close()
        raise ArchiveLockedError(
            f"recording archive is already open for writing: {path}"
        ) from error


def _open_writer_lock_file(path: Path) -> BinaryIO:
    lock_path = path.with_name(f"{path.name}.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    return os.fdopen(descriptor, "r+b", buffering=0)


def _release_writer_lock(lock_file: BinaryIO) -> None:
    with suppress(OSError, ValueError):
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    with suppress(OSError, ValueError):
        lock_file.close()


def _distribution_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _last_sequence(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) FROM events"
    ).fetchone()
    return int(row[0])


def _last_capture_anomaly_id(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute(
            "SELECT COALESCE(MAX(anomaly_id), 0) FROM capture_anomalies"
        ).fetchone()
        if row is None:
            raise ValueError("capture anomaly cutoff query returned no row")
        return _nonnegative_int(row[0], "capture anomaly cutoff ID")
    except ArchiveFormatError:
        raise
    except (IndexError, sqlite3.Error, TypeError, ValueError) as error:
        raise ArchiveFormatError("capture anomaly journal is malformed") from error


def _last_observed_at_ms(
    connection: sqlite3.Connection,
    *,
    sequence_cutoff: int | None = None,
) -> int | None:
    event_cutoff = "" if sequence_cutoff is None else " WHERE sequence <= ?"
    checkpoint_cutoff = "" if sequence_cutoff is None else " WHERE sequence <= ?"
    parameters: tuple[object, ...] = (
        () if sequence_cutoff is None else (sequence_cutoff, sequence_cutoff)
    )
    value = connection.execute(
        f"""
        SELECT MAX(observed_at_ms)
        FROM (
            SELECT observed_at_ms FROM events{event_cutoff}
            UNION ALL
            SELECT observed_at_ms FROM book_checkpoints{checkpoint_cutoff}
        )
        """,
        parameters,
    ).fetchone()[0]
    return None if value is None else int(value)


def _last_session_observed_at_ms(
    connection: sqlite3.Connection,
    session_id: int,
    *,
    sequence_cutoff: int | None = None,
) -> int | None:
    event_cutoff = "" if sequence_cutoff is None else " AND sequence <= ?"
    checkpoint_cutoff = "" if sequence_cutoff is None else " AND sequence <= ?"
    parameters: tuple[object, ...] = (
        (session_id, session_id)
        if sequence_cutoff is None
        else (session_id, sequence_cutoff, session_id, sequence_cutoff)
    )
    value = connection.execute(
        f"""
        SELECT MAX(observed_at_ms)
        FROM (
            SELECT observed_at_ms FROM events
            WHERE session_id = ?{event_cutoff}
            UNION ALL
            SELECT observed_at_ms FROM book_checkpoints
            WHERE session_id = ?{checkpoint_cutoff}
        )
        """,
        parameters,
    ).fetchone()[0]
    return None if value is None else int(value)


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _sessions_overlapping(
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


def _strict_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_strict_int(value: object, name: str) -> int | None:
    return None if value is None else _strict_int(value, name)


def _positive_int(value: object, name: str) -> int:
    parsed = _strict_int(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonnegative_timestamp(value: object, name: str) -> int:
    parsed = _strict_int(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be nonnegative")
    return parsed


def _nonnegative_int(value: object, name: str) -> int:
    return _nonnegative_timestamp(value, name)
