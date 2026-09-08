from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.errors import ArchiveFormatError
from polybot.recording.archive.features import (
    CAPTURE_ANOMALY_JOURNAL_FEATURE,
    capture_anomaly_journal_available,
)
from polybot.recording.archive.models import RecordingSession
from polybot.recording.archive.schema import (
    CAPTURE_ANOMALIES_TABLE,
    RECORDING_FEATURES_TABLE,
    SESSIONS_TABLE,
)
from polybot.recording.trim_contracts import RecordingTrimError, RecordingTrimPlan


class TrimProvenance:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def copy_capture_anomalies(
        self,
        plan: RecordingTrimPlan,
    ) -> None:
        self._connection.execute(
            f"""
            INSERT INTO {CAPTURE_ANOMALIES_TABLE} (
                {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION}, {ArchiveColumn.OBSERVED_AT_MS},
                {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.TOKEN_ID}, {ArchiveColumn.FAILURE_KIND}, {ArchiveColumn.PAYLOAD_JSON}
            )
            SELECT 1, anomaly.{ArchiveColumn.SUBSCRIPTION_GENERATION}, anomaly.{ArchiveColumn.OBSERVED_AT_MS},
                   anomaly.{ArchiveColumn.CONDITION_ID}, anomaly.{ArchiveColumn.MARKET_SLUG}, anomaly.{ArchiveColumn.TOKEN_ID},
                   anomaly.{ArchiveColumn.FAILURE_KIND}, anomaly.{ArchiveColumn.PAYLOAD_JSON}
            FROM source.{CAPTURE_ANOMALIES_TABLE} AS anomaly
            LEFT JOIN trim_slugs AS selected
              ON selected.{ArchiveColumn.MARKET_SLUG} = anomaly.{ArchiveColumn.MARKET_SLUG}
            WHERE anomaly.{ArchiveColumn.SESSION_ID} = ?
              AND anomaly.{ArchiveColumn.OBSERVED_AT_MS} >= ?
              AND anomaly.{ArchiveColumn.OBSERVED_AT_MS} <= ?
              AND (anomaly.{ArchiveColumn.MARKET_SLUG} IS NULL OR selected.{ArchiveColumn.MARKET_SLUG} IS NOT NULL)
            ORDER BY anomaly.{ArchiveColumn.ANOMALY_ID}
            """,
            (
                plan.source_session.session_id,
                plan.start_at_ms,
                plan.end_at_ms,
            ),
        )

    def preserve_capture_anomaly_provenance(
        self,
        plan: RecordingTrimPlan,
    ) -> bool:
        try:
            available = capture_anomaly_journal_available(
                self._connection,
                session_id=plan.source_session.session_id,
                schema="source",
            )
        except ArchiveFormatError as error:
            raise RecordingTrimError(
                "source recording advertises a missing capture anomaly journal"
            ) from error
        if not available:
            self._connection.execute(
                f"DELETE FROM {RECORDING_FEATURES_TABLE} WHERE {ArchiveColumn.FEATURE_NAME} = ?",
                (CAPTURE_ANOMALY_JOURNAL_FEATURE,),
            )
        return available

    def write_source_versions(
        self,
        source_session: RecordingSession,
    ) -> None:
        self._connection.execute(
            f"""
            UPDATE {SESSIONS_TABLE}
            SET {ArchiveColumn.RECORDER_VERSION} = ?, {ArchiveColumn.SDK_VERSION} = ?
            WHERE {ArchiveColumn.SESSION_ID} = 1
            """,
            (
                source_session.recorder_version,
                source_session.sdk_version,
            ),
        )
