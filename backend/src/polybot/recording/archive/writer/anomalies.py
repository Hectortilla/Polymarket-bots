"""Single-writer lifecycle and durable append operations for recordings."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.errors import (
    ArchiveIntegrityError,
    RecordingArchiveError,
)
from polybot.recording.archive.primitives import (
    _nonnegative_int,
    _nonnegative_timestamp_ms,
)
from polybot.recording.archive.schema import CAPTURE_ANOMALIES_TABLE
from polybot.recording.contracts.anomalies import CaptureAnomalyPayload
from polybot.recording.contracts.market import MarketIdentity
from polybot.recording.contracts.records import CaptureAnomalyRecord
from polybot.recording.serialization.entrypoints import capture_anomaly_json


def append_capture_anomaly(
    connection: sqlite3.Connection,
    session_id: int,
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
    _nonnegative_timestamp_ms(observed_at_ms, "capture anomaly observation")
    _nonnegative_int(
        subscription_generation,
        "capture anomaly subscription generation",
    )
    if not anomaly.matches_index_identity(identity):
        raise ArchiveIntegrityError(
            "capture anomaly identity does not match its initial fragment"
        )
    serialized = capture_anomaly_json(anomaly)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            f"""
            INSERT INTO {CAPTURE_ANOMALIES_TABLE} (
                {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION}, {ArchiveColumn.OBSERVED_AT_MS},
                {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.TOKEN_ID}, {ArchiveColumn.FAILURE_KIND},
                {ArchiveColumn.PAYLOAD_JSON}
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
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
        connection.commit()
    except (sqlite3.Error, ValueError) as error:
        connection.rollback()
        raise RecordingArchiveError("failed to append capture anomaly") from error
    return CaptureAnomalyRecord(
        anomaly_id=anomaly_id,
        session_id=session_id,
        subscription_generation=subscription_generation,
        observed_at_ms=observed_at_ms,
        identity=identity,
        anomaly=anomaly,
    )
