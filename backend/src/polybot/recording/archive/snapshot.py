"""Snapshot-bound sequence and observation queries for archive readers."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import BOOK_CHECKPOINTS_TABLE, EVENTS_TABLE

from .errors import ArchiveFormatError
from .primitives import _nonnegative_int
from .schema import CAPTURE_ANOMALIES_TABLE


def _last_sequence(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        f"SELECT COALESCE(MAX({ArchiveColumn.SEQUENCE}), 0) FROM {EVENTS_TABLE}"
    ).fetchone()
    return int(row[0])


def _last_capture_anomaly_id(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute(
            f"SELECT COALESCE(MAX({ArchiveColumn.ANOMALY_ID}), 0) FROM {CAPTURE_ANOMALIES_TABLE}"
        ).fetchone()
        if row is None:
            raise ValueError("capture anomaly cutoff query returned no row")
        return _nonnegative_int(row[0], "capture anomaly cutoff ID")
    except ArchiveFormatError:
        raise
    except (IndexError, sqlite3.Error, TypeError, ValueError) as error:
        raise ArchiveFormatError("capture anomaly journal is malformed") from error


def _last_observed_at_ms(
    connection: sqlite3.Connection,
    *,
    sequence_cutoff: int | None = None,
) -> int | None:
    event_cutoff = (
        "" if sequence_cutoff is None else f" WHERE {ArchiveColumn.SEQUENCE} <= ?"
    )
    checkpoint_cutoff = (
        "" if sequence_cutoff is None else f" WHERE {ArchiveColumn.SEQUENCE} <= ?"
    )
    parameters: tuple[object, ...] = (
        () if sequence_cutoff is None else (sequence_cutoff, sequence_cutoff)
    )
    value = connection.execute(
        f"""
        SELECT MAX({ArchiveColumn.OBSERVED_AT_MS})
        FROM (
            SELECT {ArchiveColumn.OBSERVED_AT_MS} FROM {EVENTS_TABLE}{event_cutoff}
            UNION ALL
            SELECT {ArchiveColumn.OBSERVED_AT_MS} FROM {BOOK_CHECKPOINTS_TABLE}{checkpoint_cutoff}
        )
        """,
        parameters,
    ).fetchone()[0]
    return None if value is None else int(value)


def _last_session_observed_at_ms(
    connection: sqlite3.Connection,
    session_id: int,
    *,
    sequence_cutoff: int | None = None,
) -> int | None:
    event_cutoff = (
        "" if sequence_cutoff is None else f" AND {ArchiveColumn.SEQUENCE} <= ?"
    )
    checkpoint_cutoff = (
        "" if sequence_cutoff is None else f" AND {ArchiveColumn.SEQUENCE} <= ?"
    )
    parameters: tuple[object, ...] = (
        (session_id, session_id)
        if sequence_cutoff is None
        else (session_id, sequence_cutoff, session_id, sequence_cutoff)
    )
    value = connection.execute(
        f"""
        SELECT MAX({ArchiveColumn.OBSERVED_AT_MS})
        FROM (
            SELECT {ArchiveColumn.OBSERVED_AT_MS} FROM {EVENTS_TABLE}
            WHERE {ArchiveColumn.SESSION_ID} = ?{event_cutoff}
            UNION ALL
            SELECT {ArchiveColumn.OBSERVED_AT_MS} FROM {BOOK_CHECKPOINTS_TABLE}
            WHERE {ArchiveColumn.SESSION_ID} = ?{checkpoint_cutoff}
        )
        """,
        parameters,
    ).fetchone()[0]
    return None if value is None else int(value)
