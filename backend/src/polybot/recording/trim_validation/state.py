from __future__ import annotations

import sqlite3

from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.models import RecordingSession
from polybot.recording.archive.schema import EVENTS_TABLE
from polybot.recording.contracts.book import RecordedBookLevel
from polybot.recording.contracts.kinds import BOOK_STATE_PAYLOAD_KINDS
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.records import BookCheckpoint, RecordedEvent


def checkpoint_matches_projected_state(
    checkpoint: BookCheckpoint,
    *,
    referenced_event: RecordedEvent,
    session: RecordingSession,
    market: MarketMetadataPayload,
    generation_by_token: dict[str, int],
    snapshot: BookSnapshot,
) -> bool:
    """Check immutable checkpoint fields against its projected canonical book."""
    return (
        checkpoint.session_id == session.session_id
        and checkpoint.identity.market_slug == market.market_slug
        and checkpoint.book.token_id
        in {outcome.token_id for outcome in market.outcomes}
        and checkpoint.observed_at_ms >= referenced_event.observed_at_ms
        and checkpoint.observed_at_ms >= session.started_at_ms
        and (
            session.ended_at_ms is None
            or checkpoint.observed_at_ms <= session.ended_at_ms
        )
        and generation_by_token.get(checkpoint.book.token_id)
        == checkpoint.subscription_generation
        and _book_levels_match(checkpoint.book.bids, snapshot.bids)
        and _book_levels_match(checkpoint.book.asks, snapshot.asks)
    )


def has_intervening_state_event(
    connection: sqlite3.Connection,
    checkpoint: BookCheckpoint,
) -> bool:
    placeholders = ", ".join("?" for _ in BOOK_STATE_PAYLOAD_KINDS)
    row = connection.execute(
        f"""
        SELECT 1
        FROM {EVENTS_TABLE} AS event
        WHERE event.{ArchiveColumn.SESSION_ID} = ? AND event.{ArchiveColumn.CONDITION_ID} = ?
          AND event.{ArchiveColumn.SEQUENCE} > ? AND event.{ArchiveColumn.OBSERVED_AT_MS} < ?
          AND event.{ArchiveColumn.PAYLOAD_KIND} IN ({placeholders})
        LIMIT 1
        """,
        (
            checkpoint.session_id,
            checkpoint.identity.condition_id,
            checkpoint.sequence,
            checkpoint.observed_at_ms,
            *(kind.value for kind in BOOK_STATE_PAYLOAD_KINDS),
        ),
    ).fetchone()
    return row is not None


def _book_levels_match(
    recorded_levels: tuple[RecordedBookLevel, ...],
    projected_levels: tuple[BookLevel, ...],
) -> bool:
    return {(level.price, level.size) for level in recorded_levels} == {
        (level.price, level.size) for level in projected_levels
    }
