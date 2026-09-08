"""Strict conversion between archive SQLite rows and recording contracts."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import METADATA_REVISIONS_TABLE

from ..contracts.anomalies import CaptureFailureKind
from ..contracts.kinds import PayloadKind
from ..contracts.market import (
    MarketIdentity,
    MarketMetadataPayload,
)
from ..contracts.records import (
    CaptureAnomalyRecord,
    RecordedEvent,
)
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
        f"""
        SELECT revision.{ArchiveColumn.CONDITION_ID}, revision.{ArchiveColumn.PAYLOAD_JSON}
        FROM {METADATA_REVISIONS_TABLE} AS revision
        WHERE revision.{ArchiveColumn.SEQUENCE} = (
            SELECT MAX(candidate.{ArchiveColumn.SEQUENCE})
            FROM {METADATA_REVISIONS_TABLE} AS candidate
            WHERE candidate.{ArchiveColumn.CONDITION_ID} = revision.{ArchiveColumn.CONDITION_ID}
        )
        """
    ).fetchall()
    result: dict[str, MarketMetadataPayload] = {}
    for row in rows:
        payload = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row[ArchiveColumn.PAYLOAD_JSON],
            MarketMetadataPayload,
        )
        if payload.condition_id != row[ArchiveColumn.CONDITION_ID]:
            raise ArchiveFormatError("metadata revision identity is inconsistent")
        result[payload.condition_id] = payload
    return result


def _event_from_row(row: sqlite3.Row) -> RecordedEvent:
    try:
        payload = payload_from_json(
            row[ArchiveColumn.PAYLOAD_KIND], row[ArchiveColumn.PAYLOAD_JSON]
        )
        return RecordedEvent(
            sequence=_strict_int(row[ArchiveColumn.SEQUENCE], "event sequence"),
            session_id=_strict_int(row[ArchiveColumn.SESSION_ID], "event session"),
            subscription_generation=_strict_int(
                row[ArchiveColumn.SUBSCRIPTION_GENERATION],
                "event generation",
            ),
            observed_at_ms=_strict_int(
                row[ArchiveColumn.OBSERVED_AT_MS], "event observation"
            ),
            source_timestamp_ms=_optional_strict_int(
                row[ArchiveColumn.SOURCE_TIMESTAMP_MS],
                "event source timestamp",
            ),
            identity=_identity_from_row(row),
            payload=payload,
        )
    except (TypeError, ValueError) as error:
        sequence = (
            row[ArchiveColumn.SEQUENCE]
            if ArchiveColumn.SEQUENCE in row.keys()
            else "unknown"
        )
        raise ArchiveFormatError(f"recording event {sequence} is malformed") from error


def _capture_anomaly_from_row(row: sqlite3.Row) -> CaptureAnomalyRecord:
    try:
        anomaly = capture_anomaly_from_json(row[ArchiveColumn.PAYLOAD_JSON])
        failure_kind = CaptureFailureKind(row[ArchiveColumn.FAILURE_KIND])
        if anomaly.failure_kind is not failure_kind:
            raise ValueError("capture anomaly failure kind index is inconsistent")
        identity = _identity_from_row(row)
        if identity is None:
            raise ValueError("capture anomaly has no market identity")
        if not anomaly.matches_index_identity(identity):
            raise ValueError("capture anomaly identity index is inconsistent")
        return CaptureAnomalyRecord(
            anomaly_id=_strict_int(row[ArchiveColumn.ANOMALY_ID], "capture anomaly ID"),
            session_id=_strict_int(
                row[ArchiveColumn.SESSION_ID], "capture anomaly session"
            ),
            subscription_generation=_strict_int(
                row[ArchiveColumn.SUBSCRIPTION_GENERATION],
                "capture anomaly generation",
            ),
            observed_at_ms=_strict_int(
                row[ArchiveColumn.OBSERVED_AT_MS],
                "capture anomaly observation",
            ),
            identity=identity,
            anomaly=anomaly,
        )
    except (IndexError, TypeError, ValueError) as error:
        anomaly_id = (
            row[ArchiveColumn.ANOMALY_ID]
            if ArchiveColumn.ANOMALY_ID in row.keys()
            else "unknown"
        )
        raise ArchiveFormatError(
            f"capture anomaly {anomaly_id} is malformed"
        ) from error


def _identity_from_row(row: sqlite3.Row) -> MarketIdentity | None:
    condition_id = row[ArchiveColumn.CONDITION_ID]
    market_slug = row[ArchiveColumn.MARKET_SLUG]
    token_id = (
        row[ArchiveColumn.TOKEN_ID] if ArchiveColumn.TOKEN_ID in row.keys() else None
    )
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
