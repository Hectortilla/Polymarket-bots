from __future__ import annotations

import sqlite3
from contextlib import suppress
from pathlib import Path

from polybot.recording.archive.connections import (
    SQLITE_CONNECTION_TIMEOUT_SECONDS,
    configure_writer_connection,
    readonly_database_uri,
)
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.archive.writer import RecordingArchive
from polybot.recording.trim_bootstrap import TrimBootstrap
from polybot.recording.trim_contracts import RecordingTrimError, RecordingTrimPlan
from polybot.recording.trim_export.provenance import TrimProvenance
from polybot.recording.trim_export.rows import TrimRows
from polybot.recording.trim_export.selection import create_selection_tables


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
        synthetic_event_count = TrimBootstrap(source).write(plan, archive)
        archive.close(ended_at_ms=plan.end_at_ms)
    except BaseException as error:
        with suppress(Exception):
            archive.close(clean=False, failure_reason=f"trim failed: {error}")
        raise

    TrimExporter(plan.archive_path, destination).copy(
        plan=plan,
        sequence_offset=synthetic_event_count,
    )
    return synthetic_event_count


class TrimExporter:
    def __init__(self, source_path: Path, destination_path: Path) -> None:
        self._source_path = source_path
        self._destination_path = destination_path

    def copy(
        self,
        *,
        plan: RecordingTrimPlan,
        sequence_offset: int,
    ) -> None:
        connection = sqlite3.connect(
            self._destination_path,
            timeout=SQLITE_CONNECTION_TIMEOUT_SECONDS,
            isolation_level=None,
            uri=True,
        )
        try:
            configure_writer_connection(connection)
            source_uri = readonly_database_uri(self._source_path, immutable=True)
            connection.execute("ATTACH DATABASE ? AS source", (source_uri,))
            create_selection_tables(connection, plan, sequence_offset)
            rows = TrimRows(connection)
            provenance = TrimProvenance(connection)
            connection.execute("BEGIN IMMEDIATE")
            rows.copy_events()
            rows.copy_checkpoints(
                plan=plan,
                bootstrap_sequence=sequence_offset,
            )
            if provenance.preserve_capture_anomaly_provenance(plan):
                provenance.copy_capture_anomalies(plan)
            provenance.write_source_versions(plan.source_session)
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
