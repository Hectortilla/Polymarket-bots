"""Optional archive feature registration and immutable-read provenance."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import SESSIONS_TABLE

from .errors import ArchiveFormatError
from .models import RecordingFeatureProvenance
from .primitives import _nonnegative_timestamp_ms, _positive_int, _required_text
from .provenance import RECORDER_DISTRIBUTION, distribution_version
from .schema import CAPTURE_ANOMALIES_TABLE, RECORDING_FEATURES_TABLE

CAPTURE_ANOMALY_JOURNAL_FEATURE = "capture_anomaly_journal"
_SQLITE_SCHEMAS = frozenset(("main", "source"))


def capture_anomaly_journal_available(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    schema: str = "main",
) -> bool:
    """Return feature availability and reject a missing advertised table."""

    if schema not in _SQLITE_SCHEMAS:
        raise ValueError("unsupported SQLite schema alias")
    if not _schema_table_exists(connection, schema, RECORDING_FEATURES_TABLE):
        return False
    row = connection.execute(
        f"""
        SELECT {ArchiveColumn.AVAILABLE_FROM_SESSION_ID}
        FROM {schema}.{RECORDING_FEATURES_TABLE}
        WHERE {ArchiveColumn.FEATURE_NAME} = ?
        """,
        (CAPTURE_ANOMALY_JOURNAL_FEATURE,),
    ).fetchone()
    available = row is not None and int(row[0]) <= session_id
    if available and not _schema_table_exists(
        connection,
        schema,
        CAPTURE_ANOMALIES_TABLE,
    ):
        raise ArchiveFormatError("capture anomaly journal feature table is missing")
    return available


def _enable_capture_anomaly_journal(
    connection: sqlite3.Connection,
    *,
    available_from_session_id: int,
    enabled_at_ms: int,
) -> None:
    connection.execute(
        f"""
        INSERT OR IGNORE INTO {RECORDING_FEATURES_TABLE} (
            {ArchiveColumn.FEATURE_NAME}, {ArchiveColumn.AVAILABLE_FROM_SESSION_ID}, {ArchiveColumn.ENABLED_AT_MS},
            {ArchiveColumn.RECORDER_VERSION}
        ) VALUES (?, ?, ?, ?)
        """,
        (
            CAPTURE_ANOMALY_JOURNAL_FEATURE,
            available_from_session_id,
            enabled_at_ms,
            distribution_version(RECORDER_DISTRIBUTION),
        ),
    )


def _capture_anomaly_journal_provenance(
    connection: sqlite3.Connection,
) -> RecordingFeatureProvenance | None:
    try:
        if not _table_exists(connection, RECORDING_FEATURES_TABLE):
            return None
        row = connection.execute(
            f"""
            SELECT {ArchiveColumn.FEATURE_NAME}, {ArchiveColumn.AVAILABLE_FROM_SESSION_ID}, {ArchiveColumn.ENABLED_AT_MS},
                   {ArchiveColumn.RECORDER_VERSION}
            FROM {RECORDING_FEATURES_TABLE}
            WHERE {ArchiveColumn.FEATURE_NAME} = ?
            """,
            (CAPTURE_ANOMALY_JOURNAL_FEATURE,),
        ).fetchone()
        if row is None:
            return None
        if not _table_exists(connection, CAPTURE_ANOMALIES_TABLE):
            raise ArchiveFormatError("capture anomaly journal feature table is missing")
        provenance = RecordingFeatureProvenance(
            feature_name=_required_text(
                row[ArchiveColumn.FEATURE_NAME], "feature name"
            ),
            available_from_session_id=_positive_int(
                row[ArchiveColumn.AVAILABLE_FROM_SESSION_ID],
                "feature activation session ID",
            ),
            enabled_at_ms=_nonnegative_timestamp_ms(
                row[ArchiveColumn.ENABLED_AT_MS],
                "feature activation timestamp",
            ),
            recorder_version=_required_text(
                row[ArchiveColumn.RECORDER_VERSION],
                "feature recorder version",
            ),
        )
        activation_session = connection.execute(
            f"SELECT 1 FROM {SESSIONS_TABLE} WHERE {ArchiveColumn.SESSION_ID} = ?",
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
    return _schema_table_exists(connection, "main", table_name)


def _schema_table_exists(
    connection: sqlite3.Connection,
    schema: str,
    table_name: str,
) -> bool:
    row = connection.execute(
        f"SELECT 1 FROM {schema}.sqlite_schema WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None
