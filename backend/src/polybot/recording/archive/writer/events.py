"""Single-writer lifecycle and durable append operations for recordings."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import (
    COVERAGE_GAPS_TABLE,
    EVENT_TOKENS_TABLE,
    EVENTS_TABLE,
    METADATA_REVISIONS_TABLE,
)
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.payloads import event_token_ids
from polybot.recording.contracts.records import RecordedEvent
from polybot.recording.serialization.entrypoints import payload_json
from polybot.recording.serialization.registry import payload_kind


def insert_event(connection: sqlite3.Connection, event: RecordedEvent) -> None:
    identity = event.identity
    kind = payload_kind(event.payload)
    serialized = payload_json(event.payload)
    connection.execute(
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
    connection.executemany(
        f"INSERT INTO {EVENT_TOKENS_TABLE} ({ArchiveColumn.SEQUENCE}, {ArchiveColumn.TOKEN_ID}) VALUES (?, ?)",
        ((event.sequence, token_id) for token_id in event_token_ids(event.payload)),
    )
    if isinstance(event.payload, MarketMetadataPayload):
        connection.execute(
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
        connection.execute(
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
