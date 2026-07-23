"""Optional archive feature registration and immutable-read provenance."""

from __future__ import annotations

import sqlite3

from .errors import ArchiveFormatError
from .models import RecordingFeatureProvenance
from .primitives import _nonnegative_timestamp, _positive_int, _required_text
from .provenance import RECORDER_DISTRIBUTION, distribution_version
from .schema import CAPTURE_ANOMALIES_TABLE, RECORDING_FEATURES_TABLE

CAPTURE_ANOMALY_JOURNAL_FEATURE = "capture_anomaly_journal"


def _enable_capture_anomaly_journal(
    connection: sqlite3.Connection,
    *,
    available_from_session_id: int,
    enabled_at_ms: int,
) -> None:
    connection.execute(
        f"""
        INSERT OR IGNORE INTO {RECORDING_FEATURES_TABLE} (
            feature_name, available_from_session_id, enabled_at_ms,
            recorder_version
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
            SELECT feature_name, available_from_session_id, enabled_at_ms,
                   recorder_version
            FROM {RECORDING_FEATURES_TABLE}
            WHERE feature_name = ?
            """,
            (CAPTURE_ANOMALY_JOURNAL_FEATURE,),
        ).fetchone()
        if row is None:
            return None
        if not _table_exists(connection, CAPTURE_ANOMALIES_TABLE):
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
