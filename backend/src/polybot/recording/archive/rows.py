"""Strict conversion between archive SQLite rows and recording contracts."""

from __future__ import annotations

import sqlite3

from ..contracts.records import (
    CaptureAnomalyRecord,
    RecordedEvent,
)
from ..contracts.anomalies import CaptureFailureKind
from ..contracts.market import (
    MarketIdentity,
    MarketMetadataPayload,
)
from ..contracts.kinds import PayloadKind
from ..serialization.entrypoints import (
    capture_anomaly_from_json,
    payload_from_json,
)
from .errors import ArchiveFormatError
from .primitives import _optional_strict_int, _strict_int


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
