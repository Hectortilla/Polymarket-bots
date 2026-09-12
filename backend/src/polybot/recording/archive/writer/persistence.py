"""Session-bound SQLite row writes under the archive writer lock."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.errors import (
    ArchiveIntegrityError,
    RecordingArchiveError,
)
from polybot.recording.archive.primitives import (
    _nonnegative_int,
    _nonnegative_timestamp_ms,
    _positive_int,
)
from polybot.recording.archive.rows import _typed_payload
from polybot.recording.archive.schema import (
    BOOK_CHECKPOINTS_TABLE,
    CAPTURE_ANOMALIES_TABLE,
    COVERAGE_GAPS_TABLE,
    EVENT_TOKENS_TABLE,
    EVENTS_TABLE,
    METADATA_REVISIONS_TABLE,
)
from polybot.recording.contracts.anomalies import CaptureAnomalyPayload
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.kinds import PayloadKind
from polybot.recording.contracts.market import MarketIdentity, MarketMetadataPayload
from polybot.recording.contracts.payloads import event_token_ids
from polybot.recording.contracts.records import (
    BookCheckpoint,
    CaptureAnomalyRecord,
    RecordedEvent,
)
from polybot.recording.serialization.anomalies import capture_anomaly_json
from polybot.recording.serialization.payloads import payload_json
from polybot.recording.serialization.registry import payload_kind


class ArchiveRowWriter:
    def __init__(self, connection: sqlite3.Connection, session_id: int) -> None:
        self._connection = connection
        self._session_id = session_id

    def insert_event(self, event: RecordedEvent) -> None:
        identity = event.identity
        kind = payload_kind(event.payload)
        serialized = payload_json(event.payload)
        self._connection.execute(
            f"""
            INSERT INTO {EVENTS_TABLE} (
                {ArchiveColumn.SEQUENCE}, {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION}, {ArchiveColumn.OBSERVED_AT_MS},
                {ArchiveColumn.SOURCE_TIMESTAMP_MS}, {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.TOKEN_ID},
                {ArchiveColumn.PAYLOAD_KIND}, {ArchiveColumn.PAYLOAD_JSON}
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.sequence,
                event.session_id,
                event.subscription_generation,
                event.observed_at_ms,
                event.source_timestamp_ms,
                None if identity is None else identity.condition_id,
                None if identity is None else identity.market_slug,
                None if identity is None else identity.token_id,
                kind.value,
                serialized,
            ),
        )
        self._connection.executemany(
            f"INSERT INTO {EVENT_TOKENS_TABLE} ({ArchiveColumn.SEQUENCE}, {ArchiveColumn.TOKEN_ID}) VALUES (?, ?)",
            ((event.sequence, token_id) for token_id in event_token_ids(event.payload)),
        )
        if isinstance(event.payload, MarketMetadataPayload):
            self._connection.execute(
                f"""
                INSERT INTO {METADATA_REVISIONS_TABLE} (
                    {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.SEQUENCE}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.PAYLOAD_JSON}
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    event.payload.condition_id,
                    event.sequence,
                    event.observed_at_ms,
                    serialized,
                ),
            )
        elif isinstance(event.payload, CoverageGapPayload):
            self._connection.execute(
                f"""
                INSERT INTO {COVERAGE_GAPS_TABLE} (
                    {ArchiveColumn.EVENT_SEQUENCE}, {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION},
                    {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.STARTED_AT_MS},
                    {ArchiveColumn.ENDED_AT_MS}, {ArchiveColumn.REASON}, {ArchiveColumn.PAYLOAD_JSON}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.sequence,
                    event.session_id,
                    event.subscription_generation,
                    event.observed_at_ms,
                    None if identity is None else identity.condition_id,
                    None if identity is None else identity.market_slug,
                    event.payload.started_at_ms,
                    event.payload.ended_at_ms,
                    event.payload.reason,
                    serialized,
                ),
            )

    def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        _positive_int(gap_id, "coverage gap ID")
        _nonnegative_timestamp_ms(ended_at_ms, "coverage gap end")
        row = self._connection.execute(
            f"""
            SELECT {ArchiveColumn.EVENT_SEQUENCE}, {ArchiveColumn.PAYLOAD_JSON}
            FROM {COVERAGE_GAPS_TABLE}
            WHERE {ArchiveColumn.GAP_ID} = ?
            """,
            (gap_id,),
        ).fetchone()
        if row is None:
            raise ArchiveIntegrityError(f"unknown coverage gap ID {gap_id}")
        payload = _typed_payload(
            PayloadKind.COVERAGE_GAP,
            row[ArchiveColumn.PAYLOAD_JSON],
            CoverageGapPayload,
        )
        if payload.ended_at_ms is not None:
            raise ArchiveIntegrityError("coverage gap is already closed")
        closed_payload = replace(payload, ended_at_ms=ended_at_ms)
        serialized = payload_json(closed_payload)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                f"""
                UPDATE {COVERAGE_GAPS_TABLE}
                SET {ArchiveColumn.ENDED_AT_MS} = ?, {ArchiveColumn.PAYLOAD_JSON} = ?
                WHERE {ArchiveColumn.GAP_ID} = ?
                """,
                (ended_at_ms, serialized, gap_id),
            )
            self._connection.execute(
                f"UPDATE {EVENTS_TABLE} SET {ArchiveColumn.PAYLOAD_JSON} = ? WHERE {ArchiveColumn.SEQUENCE} = ?",
                (serialized, row[ArchiveColumn.EVENT_SEQUENCE]),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            self._connection.rollback()
            raise RecordingArchiveError("failed to close coverage gap") from error

    def append_capture_anomaly(
        self,
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
            self._connection.execute("BEGIN IMMEDIATE")
            cursor = self._connection.execute(
                f"""
                INSERT INTO {CAPTURE_ANOMALIES_TABLE} (
                    {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION}, {ArchiveColumn.OBSERVED_AT_MS},
                    {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.TOKEN_ID}, {ArchiveColumn.FAILURE_KIND},
                    {ArchiveColumn.PAYLOAD_JSON}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._session_id,
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
            self._connection.commit()
        except (sqlite3.Error, ValueError) as error:
            self._connection.rollback()
            raise RecordingArchiveError("failed to append capture anomaly") from error
        return CaptureAnomalyRecord(
            anomaly_id=anomaly_id,
            session_id=self._session_id,
            subscription_generation=subscription_generation,
            observed_at_ms=observed_at_ms,
            identity=identity,
            anomaly=anomaly,
        )

    def append_checkpoints(self, pending: tuple[BookCheckpoint, ...]) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.executemany(
                f"""
                INSERT INTO {BOOK_CHECKPOINTS_TABLE} (
                    {ArchiveColumn.TOKEN_ID}, {ArchiveColumn.SEQUENCE}, {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION},
                    {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.PAYLOAD_JSON}
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        checkpoint.book.token_id,
                        checkpoint.sequence,
                        checkpoint.session_id,
                        checkpoint.subscription_generation,
                        checkpoint.observed_at_ms,
                        checkpoint.identity.condition_id,
                        checkpoint.identity.market_slug,
                        payload_json(checkpoint.book),
                    )
                    for checkpoint in pending
                ),
            )
            self._connection.commit()
        except (sqlite3.Error, ValueError) as error:
            self._connection.rollback()
            raise RecordingArchiveError("failed to append book checkpoints") from error
