from __future__ import annotations

import sqlite3
from pathlib import Path

from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.connections import readonly_database_uri
from polybot.recording.archive.models import RecordingSession
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.archive.schema import (
    BOOK_CHECKPOINTS_TABLE,
    EVENT_TOKENS_TABLE,
    METADATA_REVISIONS_TABLE,
)
from polybot.recording.contracts.book import BookBaselinePayload
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.trim_contracts import RecordingTrimError
from polybot.recording.trim_validation.indexes import (
    validate_checkpoint_index,
    validate_event_token_index,
    validate_metadata_index,
)


def validate_trimmed_rows(
    path: Path,
    reader: RecordingReader,
    session: RecordingSession,
) -> int:
    connection = sqlite3.connect(
        readonly_database_uri(path, immutable=True),
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        token_cursor = connection.execute(
            f"SELECT {ArchiveColumn.SEQUENCE}, {ArchiveColumn.TOKEN_ID} FROM {EVENT_TOKENS_TABLE} "
            f"ORDER BY {ArchiveColumn.SEQUENCE}, {ArchiveColumn.TOKEN_ID}"
        )
        revision_cursor = connection.execute(
            f"SELECT * FROM {METADATA_REVISIONS_TABLE} ORDER BY {ArchiveColumn.SEQUENCE}"
        )
        checkpoint_cursor = connection.execute(
            f"SELECT * FROM {BOOK_CHECKPOINTS_TABLE} ORDER BY {ArchiveColumn.SEQUENCE}, {ArchiveColumn.TOKEN_ID}"
        )
        token_row = token_cursor.fetchone()
        revision_row = revision_cursor.fetchone()
        checkpoint_row = checkpoint_cursor.fetchone()
        markets: dict[str, MarketMetadataPayload] = {}
        generation_by_token: dict[str, int] = {}
        state = ArchiveMarketState()
        event_count = 0
        previous_sequence = 0
        previous_observed_at_ms: int | None = None
        for event in reader.iter_events(session_id=session.session_id):
            event_count += 1
            sequence = event.sequence
            if (
                sequence <= previous_sequence
                or event.observed_at_ms < session.started_at_ms
                or (
                    session.ended_at_ms is not None
                    and event.observed_at_ms > session.ended_at_ms
                )
                or (
                    previous_observed_at_ms is not None
                    and event.observed_at_ms < previous_observed_at_ms
                )
            ):
                raise RecordingTrimError(
                    "trimmed recording event timeline is malformed"
                )
            previous_sequence = sequence
            previous_observed_at_ms = event.observed_at_ms
            token_row = validate_event_token_index(
                token_cursor,
                token_row,
                event,
            )
            revision_row = validate_metadata_index(
                revision_cursor,
                revision_row,
                event,
                markets,
            )

            if isinstance(event.payload, BookBaselinePayload):
                generation_by_token[event.payload.token_id] = (
                    event.subscription_generation
                )
            state.apply(event)
            checkpoint_row = validate_checkpoint_index(
                checkpoint_cursor,
                checkpoint_row,
                connection=connection,
                referenced_event=event,
                session=session,
                markets=markets,
                generation_by_token=generation_by_token,
                projected_books=state.books,
            )

        if (
            token_row is not None
            or revision_row is not None
            or checkpoint_row is not None
        ):
            raise RecordingTrimError(
                "trimmed recording auxiliary index contains an extra row"
            )
        if reader.capture_anomaly_journal_available(session.session_id):
            for _ in reader.iter_capture_anomalies(session_id=session.session_id):
                pass
        return event_count
    finally:
        connection.close()
