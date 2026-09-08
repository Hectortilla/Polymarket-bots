from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import (
    BOOK_CHECKPOINTS_TABLE,
    EVENT_TOKENS_TABLE,
    EVENTS_TABLE,
    METADATA_REVISIONS_TABLE,
)
from polybot.recording.trim_contracts import RecordingTrimPlan


class TrimRows:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def copy_events(self) -> None:
        self._connection.execute(
            f"""
            INSERT INTO {EVENTS_TABLE} (
                {ArchiveColumn.SEQUENCE}, {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION}, {ArchiveColumn.OBSERVED_AT_MS},
                {ArchiveColumn.SOURCE_TIMESTAMP_MS}, {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.TOKEN_ID},
                {ArchiveColumn.PAYLOAD_KIND}, {ArchiveColumn.PAYLOAD_JSON}
            )
            SELECT sequence_map.new_sequence, 1,
                   event.{ArchiveColumn.SUBSCRIPTION_GENERATION}, event.{ArchiveColumn.OBSERVED_AT_MS},
                   event.{ArchiveColumn.SOURCE_TIMESTAMP_MS}, event.{ArchiveColumn.CONDITION_ID},
                   event.{ArchiveColumn.MARKET_SLUG}, event.{ArchiveColumn.TOKEN_ID}, event.{ArchiveColumn.PAYLOAD_KIND},
                   event.{ArchiveColumn.PAYLOAD_JSON}
            FROM source.{EVENTS_TABLE} AS event
            JOIN trim_sequence_map AS sequence_map
              ON sequence_map.old_sequence = event.{ArchiveColumn.SEQUENCE}
            ORDER BY event.{ArchiveColumn.SEQUENCE}
            """
        )
        self._connection.execute(
            f"""
            INSERT INTO {EVENT_TOKENS_TABLE} ({ArchiveColumn.SEQUENCE}, {ArchiveColumn.TOKEN_ID})
            SELECT sequence_map.new_sequence, token.{ArchiveColumn.TOKEN_ID}
            FROM source.{EVENT_TOKENS_TABLE} AS token
            JOIN trim_sequence_map AS sequence_map
              ON sequence_map.old_sequence = token.{ArchiveColumn.SEQUENCE}
            """
        )
        self._connection.execute(
            f"""
            INSERT INTO {METADATA_REVISIONS_TABLE} (
                {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.SEQUENCE}, {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.PAYLOAD_JSON}
            )
            SELECT revision.{ArchiveColumn.CONDITION_ID}, sequence_map.new_sequence,
                   revision.{ArchiveColumn.OBSERVED_AT_MS}, revision.{ArchiveColumn.PAYLOAD_JSON}
            FROM source.{METADATA_REVISIONS_TABLE} AS revision
            JOIN trim_sequence_map AS sequence_map
              ON sequence_map.old_sequence = revision.{ArchiveColumn.SEQUENCE}
            """
        )

    def copy_checkpoints(
        self,
        *,
        plan: RecordingTrimPlan,
        bootstrap_sequence: int,
    ) -> None:
        self._connection.execute(
            f"""
            INSERT OR REPLACE INTO {BOOK_CHECKPOINTS_TABLE} (
                {ArchiveColumn.TOKEN_ID}, {ArchiveColumn.SEQUENCE}, {ArchiveColumn.SESSION_ID}, {ArchiveColumn.SUBSCRIPTION_GENERATION},
                {ArchiveColumn.OBSERVED_AT_MS}, {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.MARKET_SLUG}, {ArchiveColumn.PAYLOAD_JSON}
            )
            SELECT checkpoint.{ArchiveColumn.TOKEN_ID},
                   COALESCE(
                       (
                           SELECT sequence_map.new_sequence
                           FROM trim_sequence_map AS sequence_map
                           WHERE sequence_map.old_sequence <= checkpoint.{ArchiveColumn.SEQUENCE}
                           ORDER BY sequence_map.old_sequence DESC
                           LIMIT 1
                       ),
                       NULLIF(?, 0)
                   ),
                   1, checkpoint.{ArchiveColumn.SUBSCRIPTION_GENERATION},
                   checkpoint.{ArchiveColumn.OBSERVED_AT_MS}, checkpoint.{ArchiveColumn.CONDITION_ID},
                   checkpoint.{ArchiveColumn.MARKET_SLUG}, checkpoint.{ArchiveColumn.PAYLOAD_JSON}
            FROM source.{BOOK_CHECKPOINTS_TABLE} AS checkpoint
            JOIN trim_slugs AS selected
              ON selected.{ArchiveColumn.MARKET_SLUG} = checkpoint.{ArchiveColumn.MARKET_SLUG}
            WHERE checkpoint.{ArchiveColumn.SESSION_ID} = ?
              AND checkpoint.{ArchiveColumn.OBSERVED_AT_MS} >= ?
              AND checkpoint.{ArchiveColumn.OBSERVED_AT_MS} <= ?
              AND (
                  ? > 0 OR EXISTS (
                      SELECT 1
                      FROM trim_sequence_map AS sequence_map
                      WHERE sequence_map.old_sequence <= checkpoint.{ArchiveColumn.SEQUENCE}
                  )
              )
            ORDER BY checkpoint.{ArchiveColumn.OBSERVED_AT_MS}, checkpoint.{ArchiveColumn.SEQUENCE},
                     checkpoint.{ArchiveColumn.TOKEN_ID}
            """,
            (
                bootstrap_sequence,
                plan.source_session.session_id,
                plan.start_at_ms,
                plan.end_at_ms,
                bootstrap_sequence,
            ),
        )
