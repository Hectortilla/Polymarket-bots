"""SQLite export for a planned recording trim."""

from __future__ import annotations

import sqlite3
from contextlib import suppress
from pathlib import Path

from .archive.errors import ArchiveFormatError
from .archive.features import (
    CAPTURE_ANOMALY_JOURNAL_FEATURE,
    capture_anomaly_journal_available,
)
from .archive.reader import RecordingReader
from .archive.writer import RecordingArchive
from .archive.connections import (
    SQLITE_CONNECTION_TIMEOUT_SECONDS,
    configure_writer_connection,
    readonly_database_uri,
)
from .archive.models import RecordingSession
from .archive.schema import CAPTURE_ANOMALIES_TABLE, RECORDING_FEATURES_TABLE
from .contracts.kinds import PayloadKind
from .trim_bootstrap import write_trim_bootstrap
from .trim_contracts import RecordingTrimError, RecordingTrimPlan

def build_trimmed_archive(
    source: RecordingReader,
    plan: RecordingTrimPlan,
    destination: Path,
) -> int:
    archive = RecordingArchive.create(
        destination,
        target_identity=plan.target_identity,
        started_at_ms=plan.start_at_ms,
    )
    try:
        synthetic_event_count = write_trim_bootstrap(source, plan, archive)
        archive.close(ended_at_ms=plan.end_at_ms)
    except BaseException as error:
        with suppress(Exception):
            archive.close(clean=False, failure_reason=f"trim failed: {error}")
        raise

    _copy_selected_rows(
        source_path=plan.archive_path,
        destination_path=destination,
        plan=plan,
        sequence_offset=synthetic_event_count,
    )
    return synthetic_event_count


def _copy_selected_rows(
    *,
    source_path: Path,
    destination_path: Path,
    plan: RecordingTrimPlan,
    sequence_offset: int,
) -> None:
    connection = sqlite3.connect(
        destination_path,
        timeout=SQLITE_CONNECTION_TIMEOUT_SECONDS,
        isolation_level=None,
        uri=True,
    )
    try:
        configure_writer_connection(connection)
        source_uri = readonly_database_uri(source_path, immutable=True)
        connection.execute("ATTACH DATABASE ? AS source", (source_uri,))
        _create_selection_tables(connection, plan, sequence_offset)
        connection.execute("BEGIN IMMEDIATE")
        _copy_events(connection)
        _copy_checkpoints(
            connection,
            plan=plan,
            bootstrap_sequence=sequence_offset,
        )
        if _preserve_capture_anomaly_provenance(connection, plan):
            _copy_capture_anomalies(connection, plan)
        _write_source_versions(connection, plan.source_session)
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RecordingTrimError(
                "trimmed recording contains broken database references"
            )
        connection.commit()
        connection.execute("DETACH DATABASE source")
        checkpoint = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
        if checkpoint is None or int(checkpoint[0]) != 0:
            raise RecordingTrimError(
                "trimmed recording WAL could not be checkpointed"
            )
    except Exception as error:
        with suppress(sqlite3.Error):
            connection.rollback()
        if isinstance(error, RecordingTrimError):
            raise
        raise RecordingTrimError("failed to write trimmed recording") from error
    finally:
        connection.close()


def _create_selection_tables(
    connection: sqlite3.Connection,
    plan: RecordingTrimPlan,
    sequence_offset: int,
) -> None:
    connection.execute(
        "CREATE TEMP TABLE trim_slugs (market_slug TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    connection.executemany(
        "INSERT INTO trim_slugs (market_slug) VALUES (?)",
        ((slug,) for slug in plan.market_slugs),
    )
    connection.execute(
        "CREATE TEMP TABLE trim_sequence_map ("
        "old_sequence INTEGER PRIMARY KEY, "
        "new_sequence INTEGER NOT NULL UNIQUE) WITHOUT ROWID"
    )
    connection.execute(
        """
        INSERT INTO trim_sequence_map (old_sequence, new_sequence)
        SELECT event.sequence, event.sequence + ?
        FROM source.events AS event
        JOIN trim_slugs AS selected
          ON selected.market_slug = event.market_slug
        WHERE event.session_id = ?
          AND event.observed_at_ms >= ?
          AND event.observed_at_ms <= ?
          AND event.payload_kind != ?
        """,
        (
            sequence_offset,
            plan.source_session.session_id,
            plan.start_at_ms,
            plan.end_at_ms,
            PayloadKind.COVERAGE_GAP.value,
        ),
    )


def _copy_events(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO events (
            sequence, session_id, subscription_generation, observed_at_ms,
            source_timestamp_ms, condition_id, market_slug, token_id,
            payload_kind, payload_json
        )
        SELECT sequence_map.new_sequence, 1,
               event.subscription_generation, event.observed_at_ms,
               event.source_timestamp_ms, event.condition_id,
               event.market_slug, event.token_id, event.payload_kind,
               event.payload_json
        FROM source.events AS event
        JOIN trim_sequence_map AS sequence_map
          ON sequence_map.old_sequence = event.sequence
        ORDER BY event.sequence
        """
    )
    connection.execute(
        """
        INSERT INTO event_tokens (sequence, token_id)
        SELECT sequence_map.new_sequence, token.token_id
        FROM source.event_tokens AS token
        JOIN trim_sequence_map AS sequence_map
          ON sequence_map.old_sequence = token.sequence
        """
    )
    connection.execute(
        """
        INSERT INTO metadata_revisions (
            condition_id, sequence, observed_at_ms, payload_json
        )
        SELECT revision.condition_id, sequence_map.new_sequence,
               revision.observed_at_ms, revision.payload_json
        FROM source.metadata_revisions AS revision
        JOIN trim_sequence_map AS sequence_map
          ON sequence_map.old_sequence = revision.sequence
        """
    )


def _copy_checkpoints(
    connection: sqlite3.Connection,
    *,
    plan: RecordingTrimPlan,
    bootstrap_sequence: int,
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO book_checkpoints (
            token_id, sequence, session_id, subscription_generation,
            observed_at_ms, condition_id, market_slug, payload_json
        )
        SELECT checkpoint.token_id,
               COALESCE(
                   (
                       SELECT sequence_map.new_sequence
                       FROM trim_sequence_map AS sequence_map
                       WHERE sequence_map.old_sequence <= checkpoint.sequence
                       ORDER BY sequence_map.old_sequence DESC
                       LIMIT 1
                   ),
                   NULLIF(?, 0)
               ),
               1, checkpoint.subscription_generation,
               checkpoint.observed_at_ms, checkpoint.condition_id,
               checkpoint.market_slug, checkpoint.payload_json
        FROM source.book_checkpoints AS checkpoint
        JOIN trim_slugs AS selected
          ON selected.market_slug = checkpoint.market_slug
        WHERE checkpoint.session_id = ?
          AND checkpoint.observed_at_ms >= ?
          AND checkpoint.observed_at_ms <= ?
          AND (
              ? > 0 OR EXISTS (
                  SELECT 1
                  FROM trim_sequence_map AS sequence_map
                  WHERE sequence_map.old_sequence <= checkpoint.sequence
              )
          )
        ORDER BY checkpoint.observed_at_ms, checkpoint.sequence,
                 checkpoint.token_id
        """,
        (
            bootstrap_sequence,
            plan.source_session.session_id,
            plan.start_at_ms,
            plan.end_at_ms,
            bootstrap_sequence,
        ),
    )


def _copy_capture_anomalies(
    connection: sqlite3.Connection,
    plan: RecordingTrimPlan,
) -> None:
    connection.execute(
        f"""
        INSERT INTO {CAPTURE_ANOMALIES_TABLE} (
            session_id, subscription_generation, observed_at_ms,
            condition_id, market_slug, token_id, failure_kind, payload_json
        )
        SELECT 1, anomaly.subscription_generation, anomaly.observed_at_ms,
               anomaly.condition_id, anomaly.market_slug, anomaly.token_id,
               anomaly.failure_kind, anomaly.payload_json
        FROM source.{CAPTURE_ANOMALIES_TABLE} AS anomaly
        LEFT JOIN trim_slugs AS selected
          ON selected.market_slug = anomaly.market_slug
        WHERE anomaly.session_id = ?
          AND anomaly.observed_at_ms >= ?
          AND anomaly.observed_at_ms <= ?
          AND (anomaly.market_slug IS NULL OR selected.market_slug IS NOT NULL)
        ORDER BY anomaly.anomaly_id
        """,
        (
            plan.source_session.session_id,
            plan.start_at_ms,
            plan.end_at_ms,
        ),
    )


def _preserve_capture_anomaly_provenance(
    connection: sqlite3.Connection,
    plan: RecordingTrimPlan,
) -> bool:
    try:
        available = capture_anomaly_journal_available(
            connection,
            session_id=plan.source_session.session_id,
            schema="source",
        )
    except ArchiveFormatError as error:
        raise RecordingTrimError(
            "source recording advertises a missing capture anomaly journal"
        ) from error
    if not available:
        connection.execute(
            f"DELETE FROM {RECORDING_FEATURES_TABLE} WHERE feature_name = ?",
            (CAPTURE_ANOMALY_JOURNAL_FEATURE,),
        )
    return available


def _write_source_versions(
    connection: sqlite3.Connection,
    source_session: RecordingSession,
) -> None:
    connection.execute(
        """
        UPDATE sessions
        SET recorder_version = ?, sdk_version = ?
        WHERE session_id = 1
        """,
        (
            source_session.recorder_version,
            source_session.sdk_version,
        ),
    )
