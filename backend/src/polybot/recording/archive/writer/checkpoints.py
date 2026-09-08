"""Single-writer lifecycle and durable append operations for recordings."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.errors import RecordingArchiveError
from polybot.recording.archive.schema import BOOK_CHECKPOINTS_TABLE
from polybot.recording.contracts.records import BookCheckpoint
from polybot.recording.serialization.entrypoints import payload_json


def append_checkpoints(
    connection: sqlite3.Connection, pending: tuple[BookCheckpoint, ...]
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
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
        connection.commit()
    except (sqlite3.Error, ValueError) as error:
        connection.rollback()
        raise RecordingArchiveError("failed to append book checkpoints") from error
