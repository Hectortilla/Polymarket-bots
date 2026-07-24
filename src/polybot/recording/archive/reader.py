"""Immutable archive-reader lifecycle and public query coordination."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import suppress
from pathlib import Path
from threading import RLock
from typing import BinaryIO

from ..contracts.anomalies import CaptureFailureKind
from ..contracts.market import MarketMetadataPayload
from ..contracts.records import (
    BookCheckpoint,
    CaptureAnomalyRecord,
    CoverageGapRecord,
    RecordedEvent,
)
from .anomalies import (
    capture_anomaly_journal_available as _capture_anomaly_journal_available,
    iter_capture_anomalies as _iter_capture_anomalies,
)
from .baselines import (
    first_complete_baseline_pair_at_or_after as _first_baseline_pair,
    has_complete_baseline_pair as _has_baseline_pair,
)
from .checkpoints import (
    checkpoint_before as _checkpoint_before,
    checkpoint_pair_at as _checkpoint_pair_at,
    checkpoint_pair_at_or_after as _checkpoint_pair_at_or_after,
    checkpoint_pair_before as _checkpoint_pair_before,
)
from .connections import configure_writer_connection
from .coverage import coverage_gaps as _coverage_gaps
from .coverage import reject_known_gaps as _reject_known_gaps
from .errors import ArchiveClosedError, ArchiveFormatError
from .events import event_bounds as _event_bounds
from .events import event_count as _event_count
from .events import stream_events as _stream_events
from .features import _capture_anomaly_journal_provenance
from .format import _validate_archive
from .lifecycle import (
    _acquire_writer_lock,
    _archive_path,
    _checkpoint_wal,
    _open_connection,
    _open_readonly_connection,
    _open_writer_lock_file,
    _release_writer_lock,
)
from .markets import (
    market_at as _market_at,
    market_slugs_with_metadata_revisions as _market_slugs_with_metadata_revisions,
    market_state_at as _market_state_at,
    markets_at as _markets_at,
    unresolved_markets as _unresolved_markets,
)
from .models import (
    RecordingEventBounds,
    RecordingFeatureProvenance,
    RecordingSession,
    RecordingSessionStatistics,
)
from .primitives import _nonnegative_timestamp, _positive_int, _required_text
from .schema import SCHEMA_VERSION
from .selection import _selection
from .sessions import _recover_interrupted_session, _session_from_row
from .sessions import select_session as _select_session
from .snapshot import (
    _last_capture_anomaly_id,
    _last_observed_at_ms,
    _last_sequence,
    _last_session_observed_at_ms,
)
from .statistics import read_recording_statistics


class RecordingReader:
    """Read one validated recording snapshot through semantic query domains."""

    def __init__(
        self,
        path: str | Path,
        *,
        _replay_lock_file: BinaryIO | None = None,
        _validated_target_identity: str | None = None,
    ) -> None:
        self._path = _archive_path(path)
        if _validated_target_identity is not None and _replay_lock_file is None:
            raise ValueError(
                "prevalidated archive identity requires an exclusive replay lease"
            )
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
            self._target_identity = (
                _validate_archive(self._connection)
                if _validated_target_identity is None
                else _validated_target_identity
            )
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
            configure_writer_connection(connection)
            target_identity = _validate_archive(connection)
            _recover_interrupted_session(connection)
            _checkpoint_wal(connection)
            connection.close()
            connection = None
            return cls(
                archive_path,
                _replay_lock_file=lock_file,
                _validated_target_identity=target_identity,
            )
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
            return _stream_events(
                path=self._path,
                immutable=self._immutable,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                selection=selection,
                allow_gaps=allow_gaps,
            )

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
            return _event_bounds(
                path=self._path,
                immutable=self._immutable,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                selection=selection,
                allow_gaps=allow_gaps,
            )

    def event_count(
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
    ) -> int:
        """Count non-gap events in one validated reader selection."""

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
            return _event_count(
                path=self._path,
                immutable=self._immutable,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                selection=selection,
                allow_gaps=allow_gaps,
            )

    def market_slugs_with_metadata_revisions(
        self,
        *,
        start_at_ms: int,
        end_at_ms: int,
        session_id: int,
        market_slugs: Iterable[str] | None = None,
        allow_gaps: bool = False,
    ) -> tuple[str, ...]:
        """Return selected slugs whose metadata changed inside the selection."""

        selection = _selection(
            start_at_ms=start_at_ms,
            end_at_ms=end_at_ms,
            session_id=session_id,
            condition_id=None,
            condition_ids=None,
            market_slug=None,
            market_slugs=market_slugs,
            token_id=None,
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
                    _reject_known_gaps(
                        connection,
                        replay_cutoff_sequence=self._replay_cutoff_sequence,
                        **selection,
                    )
                return _market_slugs_with_metadata_revisions(
                    connection,
                    replay_cutoff_sequence=self._replay_cutoff_sequence,
                    start_at_ms=start_at_ms,
                    end_at_ms=end_at_ms,
                    session_id=session_id,
                    selection=selection,
                )
            finally:
                connection.close()

    def select_session(self, session_id: int | None = None) -> RecordingSession:
        """Select one session, requiring an ID when the archive is ambiguous."""

        with self._lock:
            self._ensure_open()
            return _select_session(self._sessions, session_id)

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
                _reject_known_gaps(
                    self._connection,
                    replay_cutoff_sequence=self._replay_cutoff_sequence,
                    start_at_ms=observed_at_ms,
                    end_at_ms=observed_at_ms,
                    session_id=None,
                    condition_ids=(normalized_condition,),
                    market_slugs=None,
                    token_id=None,
                )
            return _market_at(
                self._connection,
                normalized_condition,
                observed_at_ms,
                sequence_cutoff=self._replay_cutoff_sequence,
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
                _reject_known_gaps(
                    self._connection,
                    replay_cutoff_sequence=self._replay_cutoff_sequence,
                    **selection,
                )
            return _markets_at(
                self._connection,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                observed_at_ms=observed_at_ms,
                selection=selection,
            )

    def market_state_at(
        self,
        condition_id: str,
        observed_at_ms: int,
        *,
        sequence_cutoff: int | None = None,
        allow_gaps: bool = False,
    ) -> MarketMetadataPayload | None:
        """Return metadata plus the latest ordered tick and resolution state."""

        normalized_condition = _required_text(condition_id, "condition ID")
        _nonnegative_timestamp(observed_at_ms, "market-state timestamp")
        normalized_cutoff = (
            self._replay_cutoff_sequence
            if sequence_cutoff is None
            else _positive_int(sequence_cutoff, "market-state sequence cutoff")
        )
        if normalized_cutoff > self._replay_cutoff_sequence:
            raise ValueError("market-state sequence cutoff exceeds the replay cutoff")
        with self._lock:
            self._ensure_open()
            if not allow_gaps:
                _reject_known_gaps(
                    self._connection,
                    replay_cutoff_sequence=self._replay_cutoff_sequence,
                    start_at_ms=observed_at_ms,
                    end_at_ms=observed_at_ms,
                    session_id=None,
                    condition_ids=(normalized_condition,),
                    market_slugs=None,
                    token_id=None,
                )
            return _market_state_at(
                self._connection,
                normalized_condition,
                observed_at_ms,
                sequence_cutoff=normalized_cutoff,
            )

    def has_complete_baseline_pair(
        self,
        market: MarketMetadataPayload,
        *,
        start_at_ms: int,
        end_at_ms: int,
        session_id: int | None = None,
        after_sequence_by_token: Mapping[str, int] | None = None,
    ) -> bool:
        """Return whether one generation baselines both market tokens in-range."""

        with self._lock:
            self._ensure_open()
            return _has_baseline_pair(
                self._connection,
                market,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
                session_id=session_id,
                after_sequence_by_token=after_sequence_by_token,
            )

    def first_complete_baseline_pair_at_or_after(
        self,
        market: MarketMetadataPayload,
        *,
        start_at_ms: int,
        end_at_ms: int,
        session_id: int | None = None,
        after_sequence_by_token: Mapping[str, int] | None = None,
    ) -> int | None:
        """Return the earliest in-range time both token baselines are available."""

        with self._lock:
            self._ensure_open()
            return _first_baseline_pair(
                self._connection,
                market,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
                session_id=session_id,
                after_sequence_by_token=after_sequence_by_token,
            )

    def checkpoint_before(
        self,
        token_id: str,
        observed_at_ms: int,
        *,
        session_id: int | None = None,
        allow_gaps: bool = False,
    ) -> BookCheckpoint | None:
        with self._lock:
            self._ensure_open()
            return _checkpoint_before(
                self._connection,
                token_id,
                observed_at_ms,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                session_id=session_id,
                allow_gaps=allow_gaps,
            )

    def checkpoint_pair_before(
        self,
        condition_id: str,
        observed_at_ms: int,
        *,
        session_id: int | None = None,
        allow_gaps: bool = False,
    ) -> tuple[BookCheckpoint, BookCheckpoint] | None:
        """Return the newest same-boundary checkpoint for both market tokens."""

        with self._lock:
            self._ensure_open()
            return _checkpoint_pair_before(
                self._connection,
                condition_id,
                observed_at_ms,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                session_id=session_id,
                allow_gaps=allow_gaps,
            )

    def checkpoint_pair_at(
        self,
        condition_id: str,
        observed_at_ms: int,
        *,
        session_id: int | None = None,
        allow_gaps: bool = False,
    ) -> tuple[BookCheckpoint, BookCheckpoint] | None:
        """Return a common pair only when it is exactly on one time boundary."""

        with self._lock:
            self._ensure_open()
            return _checkpoint_pair_at(
                self._connection,
                condition_id,
                observed_at_ms,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                session_id=session_id,
                allow_gaps=allow_gaps,
            )

    def checkpoint_pair_at_or_after(
        self,
        condition_id: str,
        observed_at_ms: int,
        *,
        end_at_ms: int,
        session_id: int | None = None,
        allow_gaps: bool = False,
    ) -> tuple[BookCheckpoint, BookCheckpoint] | None:
        """Return the first common pair inside one inclusive time range."""

        with self._lock:
            self._ensure_open()
            return _checkpoint_pair_at_or_after(
                self._connection,
                condition_id,
                observed_at_ms,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                end_at_ms=end_at_ms,
                session_id=session_id,
                allow_gaps=allow_gaps,
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
            return _coverage_gaps(
                self._connection,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                open_only=open_only,
                **selection,
            )

    def capture_anomaly_journal_available(self, session_id: int) -> bool:
        with self._lock:
            self._ensure_open()
            return _capture_anomaly_journal_available(
                self._sessions,
                self._capture_anomaly_provenance,
                session_id,
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

        return tuple(
            self.iter_capture_anomalies(
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
                session_id=session_id,
                condition_id=condition_id,
                market_slug=market_slug,
                failure_kind=failure_kind,
            )
        )

    def iter_capture_anomalies(
        self,
        *,
        start_at_ms: int | None = None,
        end_at_ms: int | None = None,
        session_id: int | None = None,
        condition_id: str | None = None,
        market_slug: str | None = None,
        failure_kind: CaptureFailureKind | str | None = None,
    ) -> Iterator[CaptureAnomalyRecord]:
        """Stream quarantined diagnostics from an immutable reader snapshot."""

        with self._lock:
            self._ensure_open()
            return _iter_capture_anomalies(
                path=self._path,
                immutable=self._immutable,
                sessions=self._sessions,
                replay_cutoff_id=self._capture_anomaly_cutoff_id,
                provenance=self._capture_anomaly_provenance,
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
                session_id=session_id,
                condition_id=condition_id,
                market_slug=market_slug,
                failure_kind=failure_kind,
            )

    def sessions(self) -> tuple[RecordingSession, ...]:
        with self._lock:
            self._ensure_open()
            return self._sessions

    def statistics(self) -> tuple[RecordingSessionStatistics, ...]:
        """Summarize the immutable reader snapshot without decoding event JSON."""

        with self._lock:
            self._ensure_open()
            return read_recording_statistics(
                self._connection,
                sessions=self._sessions,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                anomaly_cutoff_id=self._capture_anomaly_cutoff_id,
                anomaly_provenance=self._capture_anomaly_provenance,
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
            return _unresolved_markets(
                self._connection,
                replay_cutoff_sequence=self._replay_cutoff_sequence,
                at_ms=at_ms,
            )

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

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArchiveClosedError("recording reader is closed")
