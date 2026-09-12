"""Single-writer lifecycle and durable append operations for recordings."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from threading import RLock

from polybot.framework.clock import system_now_ms
from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.errors import (
    ArchiveClosedError,
    ArchiveIntegrityError,
    RecordingArchiveError,
)
from polybot.recording.archive.integrity import (
    _invalidate_gap_baselines,
    _validate_event_dependencies,
)
from polybot.recording.archive.lifecycle import _release_writer_lock
from polybot.recording.archive.primitives import (
    _nonnegative_timestamp_ms,
    _required_text,
)
from polybot.recording.archive.schema import (
    COVERAGE_GAPS_TABLE,
    EVENTS_TABLE,
    SESSIONS_TABLE,
)
from polybot.recording.contracts.anomalies import CaptureAnomalyPayload
from polybot.recording.contracts.book import BookBaselinePayload
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.market import MarketIdentity, MarketMetadataPayload
from polybot.recording.contracts.records import (
    BookCheckpoint,
    CaptureAnomalyRecord,
    RecordedEvent,
)
from polybot.recording.contracts.session import SessionState

from .lifecycle import ArchiveSession, create_session, resume_session
from .persistence import ArchiveRowWriter


class RecordingArchive:
    """Single-writer recording archive with process and thread serialization."""

    def __init__(self, session: ArchiveSession) -> None:
        self._path = session.path
        self._connection = session.connection
        self._lock_file = session.lock_file
        self._target_identity = session.target_identity
        self._session_id = session.session_id
        self._rows = ArchiveRowWriter(self._connection, self._session_id)
        self._session_started_at_ms = session.session_started_at_ms
        self._next_sequence = session.next_sequence
        self._last_observed_at_ms = session.last_observed_at_ms
        self._resume_from_ms = session.resume_from_ms
        self._metadata_by_condition = session.metadata_by_condition
        self._baseline_generations: set[tuple[int, str]] = set()
        self._has_gap = session.has_gap
        self._closed = False
        self._lock = RLock()

    @classmethod
    def create(
        cls, path: str | Path, *, target_identity: str, started_at_ms: int
    ) -> RecordingArchive:
        return cls(
            create_session(
                path, target_identity=target_identity, started_at_ms=started_at_ms
            )
        )

    @classmethod
    def resume(
        cls, path: str | Path, *, target_identity: str, started_at_ms: int
    ) -> RecordingArchive:
        return cls(
            resume_session(
                path, target_identity=target_identity, started_at_ms=started_at_ms
            )
        )

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
                f"SELECT COALESCE(MAX({ArchiveColumn.SUBSCRIPTION_GENERATION}), -1) + 1 FROM {EVENTS_TABLE}"
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
                    self._rows.insert_event(event)
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
                f"SELECT {ArchiveColumn.GAP_ID} FROM {COVERAGE_GAPS_TABLE} WHERE {ArchiveColumn.EVENT_SEQUENCE} = ?",
                (event.sequence,),
            ).fetchone()
            if row is None:
                raise ArchiveIntegrityError("coverage gap was not indexed")
            return int(row[0])

    def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        with self._lock:
            self._ensure_open()
            return self._rows.close_gap(gap_id, ended_at_ms=ended_at_ms)

    def append_capture_anomaly(
        self,
        anomaly: CaptureAnomalyPayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity,
        subscription_generation: int,
    ) -> CaptureAnomalyRecord:
        with self._lock:
            self._ensure_open()
            return self._rows.append_capture_anomaly(
                anomaly,
                observed_at_ms=observed_at_ms,
                identity=identity,
                subscription_generation=subscription_generation,
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
            self._rows.append_checkpoints(pending)
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
                _nonnegative_timestamp_ms(ended_at_ms, "archive end")
                if ended_at_ms < durable_boundary_ms:
                    raise ValueError("archive end cannot precede its durable boundary")
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
                    f"""
                    UPDATE {SESSIONS_TABLE}
                    SET {ArchiveColumn.ENDED_AT_MS} = ?, {ArchiveColumn.CLEAN_CLOSE} = ?, {ArchiveColumn.INTEGRITY_STATUS} = ?,
                        {ArchiveColumn.FAILURE_REASON} = ?
                    WHERE {ArchiveColumn.SESSION_ID} = ?
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

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArchiveClosedError("recording archive is closed")
