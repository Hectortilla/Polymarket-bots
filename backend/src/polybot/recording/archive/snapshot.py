"""Snapshot-bound sequence and observation queries for archive readers."""

from __future__ import annotations

import sqlite3

from .errors import ArchiveFormatError
from .primitives import _nonnegative_int
from .schema import CAPTURE_ANOMALIES_TABLE


def _last_sequence(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence), 0) FROM events"
    ).fetchone()
    return int(row[0])


def _last_capture_anomaly_id(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute(
            f"SELECT COALESCE(MAX(anomaly_id), 0) FROM {CAPTURE_ANOMALIES_TABLE}"
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
    event_cutoff = "" if sequence_cutoff is None else " WHERE sequence <= ?"
    checkpoint_cutoff = "" if sequence_cutoff is None else " WHERE sequence <= ?"
    parameters: tuple[object, ...] = (
        () if sequence_cutoff is None else (sequence_cutoff, sequence_cutoff)
    )
    value = connection.execute(
        f"""
        SELECT MAX(observed_at_ms)
        FROM (
            SELECT observed_at_ms FROM events{event_cutoff}
            UNION ALL
            SELECT observed_at_ms FROM book_checkpoints{checkpoint_cutoff}
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
    event_cutoff = "" if sequence_cutoff is None else " AND sequence <= ?"
    checkpoint_cutoff = "" if sequence_cutoff is None else " AND sequence <= ?"
    parameters: tuple[object, ...] = (
        (session_id, session_id)
        if sequence_cutoff is None
        else (session_id, sequence_cutoff, session_id, sequence_cutoff)
    )
    value = connection.execute(
        f"""
        SELECT MAX(observed_at_ms)
        FROM (
            SELECT observed_at_ms FROM events
            WHERE session_id = ?{event_cutoff}
            UNION ALL
            SELECT observed_at_ms FROM book_checkpoints
            WHERE session_id = ?{checkpoint_cutoff}
        )
        """,
        parameters,
    ).fetchone()[0]
    return None if value is None else int(value)
