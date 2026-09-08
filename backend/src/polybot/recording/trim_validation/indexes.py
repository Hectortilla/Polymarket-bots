from __future__ import annotations

import sqlite3

from polybot.framework.events.books import BookSnapshot
from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.models import RecordingSession
from polybot.recording.contracts.book import BookBaselinePayload
from polybot.recording.contracts.kinds import PayloadKind
from polybot.recording.contracts.market import MarketIdentity, MarketMetadataPayload
from polybot.recording.contracts.payloads import event_token_ids
from polybot.recording.contracts.records import BookCheckpoint, RecordedEvent
from polybot.recording.serialization.entrypoints import payload_from_json, payload_json
from polybot.recording.trim_contracts import RecordingTrimError
from polybot.recording.trim_validation.state import (
    checkpoint_matches_projected_state,
    has_intervening_state_event,
)


def validate_event_token_index(
    cursor: sqlite3.Cursor,
    row: sqlite3.Row | None,
    event: RecordedEvent,
) -> sqlite3.Row | None:
    """Validate and consume token-index rows for one recorded event."""
    sequence = event.sequence
    if row is not None and int(row[ArchiveColumn.SEQUENCE]) < sequence:
        raise RecordingTrimError(
            "trimmed recording token index references an unselected event"
        )
    actual_tokens: list[str] = []
    while row is not None and int(row[ArchiveColumn.SEQUENCE]) == sequence:
        actual_tokens.append(str(row[ArchiveColumn.TOKEN_ID]))
        row = cursor.fetchone()
    if tuple(actual_tokens) != tuple(sorted(event_token_ids(event.payload))):
        raise RecordingTrimError(
            f"trimmed recording token index is inconsistent at event {sequence}"
        )
    return row


def validate_metadata_index(
    cursor: sqlite3.Cursor,
    row: sqlite3.Row | None,
    event: RecordedEvent,
    markets: dict[str, MarketMetadataPayload],
) -> sqlite3.Row | None:
    """Validate and consume the optional metadata revision for one event."""
    sequence = event.sequence
    if row is not None and int(row[ArchiveColumn.SEQUENCE]) < sequence:
        raise RecordingTrimError(
            "trimmed recording metadata index references an unselected event"
        )
    if isinstance(event.payload, MarketMetadataPayload):
        if (
            row is None
            or int(row[ArchiveColumn.SEQUENCE]) != sequence
            or row[ArchiveColumn.CONDITION_ID] != event.payload.condition_id
            or int(row[ArchiveColumn.OBSERVED_AT_MS]) != event.observed_at_ms
            or row[ArchiveColumn.PAYLOAD_JSON] != payload_json(event.payload)
        ):
            raise RecordingTrimError(
                f"trimmed recording metadata index is inconsistent at event {sequence}"
            )
        markets[event.payload.condition_id] = event.payload
        return cursor.fetchone()
    if row is not None and int(row[ArchiveColumn.SEQUENCE]) == sequence:
        raise RecordingTrimError(
            f"trimmed recording metadata index points to event {sequence}"
        )
    return row


def validate_checkpoint_index(
    cursor: sqlite3.Cursor,
    row: sqlite3.Row | None,
    *,
    connection: sqlite3.Connection,
    referenced_event: RecordedEvent,
    session: RecordingSession,
    markets: dict[str, MarketMetadataPayload],
    generation_by_token: dict[str, int],
    projected_books: dict[str, BookSnapshot],
) -> sqlite3.Row | None:
    """Validate and consume checkpoints attached to one recorded event."""
    sequence = referenced_event.sequence
    if row is not None and int(row[ArchiveColumn.SEQUENCE]) < sequence:
        raise RecordingTrimError(
            "trimmed recording checkpoint references an unselected event"
        )
    while row is not None and int(row[ArchiveColumn.SEQUENCE]) == sequence:
        _validate_checkpoint_row(
            row,
            connection=connection,
            referenced_event=referenced_event,
            session=session,
            markets=markets,
            generation_by_token=generation_by_token,
            projected_books=projected_books,
        )
        row = cursor.fetchone()
    return row


def _validate_checkpoint_row(
    row: sqlite3.Row,
    *,
    connection: sqlite3.Connection,
    referenced_event: RecordedEvent,
    session: RecordingSession,
    markets: dict[str, MarketMetadataPayload],
    generation_by_token: dict[str, int],
    projected_books: dict[str, BookSnapshot],
) -> None:
    try:
        book = payload_from_json(
            PayloadKind.BOOK_BASELINE, row[ArchiveColumn.PAYLOAD_JSON]
        )
        if not isinstance(book, BookBaselinePayload):
            raise ValueError("checkpoint payload has a wrong type")
        checkpoint = BookCheckpoint(
            sequence=int(row[ArchiveColumn.SEQUENCE]),
            session_id=int(row[ArchiveColumn.SESSION_ID]),
            subscription_generation=int(row[ArchiveColumn.SUBSCRIPTION_GENERATION]),
            observed_at_ms=int(row[ArchiveColumn.OBSERVED_AT_MS]),
            identity=MarketIdentity(
                condition_id=row[ArchiveColumn.CONDITION_ID],
                market_slug=row[ArchiveColumn.MARKET_SLUG],
                token_id=row[ArchiveColumn.TOKEN_ID],
            ),
            book=book,
        )
        market = markets.get(checkpoint.identity.condition_id or "")
        snapshot = projected_books.get(checkpoint.book.token_id)
        if market is None:
            raise ValueError("checkpoint has no preceding metadata")
        if snapshot is None:
            raise ValueError("checkpoint has no canonical book state")
        if not checkpoint_matches_projected_state(
            checkpoint,
            referenced_event=referenced_event,
            session=session,
            market=market,
            generation_by_token=generation_by_token,
            snapshot=snapshot,
        ) or has_intervening_state_event(connection, checkpoint):
            raise ValueError("checkpoint state is inconsistent")
    except (TypeError, ValueError) as error:
        raise RecordingTrimError("trimmed recording checkpoint is malformed") from error
