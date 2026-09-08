from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import EVENTS_TABLE
from polybot.recording.contracts.kinds import PayloadKind
from polybot.recording.trim_contracts import RecordingTrimPlan


def create_selection_tables(
    connection: sqlite3.Connection,
    plan: RecordingTrimPlan,
    sequence_offset: int,
) -> None:
    connection.execute(
        f"CREATE TEMP TABLE trim_slugs ({ArchiveColumn.MARKET_SLUG} TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    connection.executemany(
        f"INSERT INTO trim_slugs ({ArchiveColumn.MARKET_SLUG}) VALUES (?)",
        ((slug,) for slug in plan.market_slugs),
    )
    connection.execute(
        "CREATE TEMP TABLE trim_sequence_map ("
        "old_sequence INTEGER PRIMARY KEY, "
        "new_sequence INTEGER NOT NULL UNIQUE) WITHOUT ROWID"
    )
    connection.execute(
        f"""
        INSERT INTO trim_sequence_map (old_sequence, new_sequence)
        SELECT event.{ArchiveColumn.SEQUENCE}, event.{ArchiveColumn.SEQUENCE} + ?
        FROM source.{EVENTS_TABLE} AS event
        JOIN trim_slugs AS selected
          ON selected.{ArchiveColumn.MARKET_SLUG} = event.{ArchiveColumn.MARKET_SLUG}
        WHERE event.{ArchiveColumn.SESSION_ID} = ?
          AND event.{ArchiveColumn.OBSERVED_AT_MS} >= ?
          AND event.{ArchiveColumn.OBSERVED_AT_MS} <= ?
          AND event.{ArchiveColumn.PAYLOAD_KIND} != ?
        """,
        (
            sequence_offset,
            plan.source_session.session_id,
            plan.start_at_ms,
            plan.end_at_ms,
            PayloadKind.COVERAGE_GAP.value,
        ),
    )
