"""Single-writer lifecycle and durable append operations for recordings."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.errors import (
    ArchiveIntegrityError,
    RecordingArchiveError,
)
from polybot.recording.archive.primitives import (
    _nonnegative_timestamp_ms,
    _positive_int,
)
from polybot.recording.archive.rows import _typed_payload
from polybot.recording.archive.schema import COVERAGE_GAPS_TABLE, EVENTS_TABLE
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.kinds import PayloadKind
from polybot.recording.serialization.entrypoints import payload_json


def close_gap(connection: sqlite3.Connection, gap_id: int, *, ended_at_ms: int) -> None:
    _positive_int(gap_id, "coverage gap ID")
    _nonnegative_timestamp_ms(ended_at_ms, "coverage gap end")
    row = connection.execute(
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
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            f"""
            UPDATE {COVERAGE_GAPS_TABLE}
            SET {ArchiveColumn.ENDED_AT_MS} = ?, {ArchiveColumn.PAYLOAD_JSON} = ?
            WHERE {ArchiveColumn.GAP_ID} = ?
            """,
            (ended_at_ms, serialized, gap_id),
        )
        connection.execute(
            f"UPDATE {EVENTS_TABLE} SET {ArchiveColumn.PAYLOAD_JSON} = ? WHERE {ArchiveColumn.SEQUENCE} = ?",
            (serialized, row[ArchiveColumn.EVENT_SEQUENCE]),
        )
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        raise RecordingArchiveError("failed to close coverage gap") from error
