"""Semantic validation for a derived recording trim artifact."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from polybot.backtesting.contracts import BacktestOptions
from polybot.backtesting.selection import (
    resolve_backtest_selection,
    validate_backtest_selection_coverage,
)
from polybot.backtesting.state import ArchiveMarketState
from polybot.framework.events.books import BookSnapshot

from .archive import RecordingReader
from .archive_models import RecordingSession
from .contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    MarketIdentity,
    MarketMetadataPayload,
    RecordedEvent,
)
from .serialization import (
    PayloadKind,
    event_token_ids,
    payload_from_json,
    payload_json,
)
from .trim_contracts import RecordingTrimError, RecordingTrimPlan


def validate_trimmed_archive(
    path: Path,
    plan: RecordingTrimPlan,
    *,
    expected_event_count: int,
) -> None:
    with RecordingReader.for_replay(path) as reader:
        sessions = reader.sessions()
        if len(sessions) != 1:
            raise RecordingTrimError(
                "trimmed recording does not contain exactly one session"
            )
        session = sessions[0]
        if (
            session.started_at_ms != plan.start_at_ms
            or session.ended_at_ms != plan.end_at_ms
        ):
            raise RecordingTrimError(
                "trimmed recording session bounds do not match the selected interval"
            )
        if reader.coverage_gaps():
            raise RecordingTrimError(
                "trimmed recording unexpectedly contains coverage gaps"
            )
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        validate_backtest_selection_coverage(reader, selection)
        if selection.market_slugs != plan.market_slugs:
            raise RecordingTrimError(
                "trimmed recording market selection changed during export"
            )
        if (
            selection.start_at_ms != plan.start_at_ms
            or selection.end_at_ms != plan.end_at_ms
        ):
            raise RecordingTrimError(
                "trimmed recording default range changed during export"
            )
        event_count = _validate_trimmed_rows(path, reader, session)
        if event_count != expected_event_count:
            raise RecordingTrimError(
                "trimmed recording event count changed during export"
            )


def _validate_trimmed_rows(
    path: Path,
    reader: RecordingReader,
    session: RecordingSession,
) -> int:
    connection = sqlite3.connect(
        f"file:{quote(str(path))}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        token_cursor = connection.execute(
            "SELECT sequence, token_id FROM event_tokens "
            "ORDER BY sequence, token_id"
        )
        revision_cursor = connection.execute(
            "SELECT * FROM metadata_revisions ORDER BY sequence"
        )
        checkpoint_cursor = connection.execute(
            "SELECT * FROM book_checkpoints ORDER BY sequence, token_id"
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
            if token_row is not None and int(token_row["sequence"]) < sequence:
                raise RecordingTrimError(
                    "trimmed recording token index references an unselected event"
                )
            actual_tokens: list[str] = []
            while token_row is not None and int(token_row["sequence"]) == sequence:
                actual_tokens.append(str(token_row["token_id"]))
                token_row = token_cursor.fetchone()
            if tuple(actual_tokens) != tuple(sorted(event_token_ids(event.payload))):
                raise RecordingTrimError(
                    f"trimmed recording token index is inconsistent at event {sequence}"
                )

            if revision_row is not None and int(revision_row["sequence"]) < sequence:
                raise RecordingTrimError(
                    "trimmed recording metadata index references an unselected event"
                )
            if isinstance(event.payload, MarketMetadataPayload):
                if (
                    revision_row is None
                    or int(revision_row["sequence"]) != sequence
                    or revision_row["condition_id"] != event.payload.condition_id
                    or int(revision_row["observed_at_ms"]) != event.observed_at_ms
                    or revision_row["payload_json"] != payload_json(event.payload)
                ):
                    raise RecordingTrimError(
                        "trimmed recording metadata index is inconsistent at "
                        f"event {sequence}"
                    )
                markets[event.payload.condition_id] = event.payload
                revision_row = revision_cursor.fetchone()
            elif (
                revision_row is not None
                and int(revision_row["sequence"]) == sequence
            ):
                raise RecordingTrimError(
                    f"trimmed recording metadata index points to event {sequence}"
                )

            if isinstance(event.payload, BookBaselinePayload):
                generation_by_token[event.payload.token_id] = (
                    event.subscription_generation
                )
            state.apply(event)
            if (
                checkpoint_row is not None
                and int(checkpoint_row["sequence"]) < sequence
            ):
                raise RecordingTrimError(
                    "trimmed recording checkpoint references an unselected event"
                )
            while (
                checkpoint_row is not None
                and int(checkpoint_row["sequence"]) == sequence
            ):
                _validate_checkpoint_row(
                    checkpoint_row,
                    connection=connection,
                    referenced_event=event,
                    session=session,
                    markets=markets,
                    generation_by_token=generation_by_token,
                    projected_books=state.books,
                )
                checkpoint_row = checkpoint_cursor.fetchone()

        if (
            token_row is not None
            or revision_row is not None
            or checkpoint_row is not None
        ):
            raise RecordingTrimError(
                "trimmed recording auxiliary index contains an extra row"
            )
        if reader.capture_anomaly_journal_available(session.session_id):
            for _ in reader.iter_capture_anomalies(
                session_id=session.session_id
            ):
                pass
        return event_count
    finally:
        connection.close()


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
        book = payload_from_json(PayloadKind.BOOK_BASELINE, row["payload_json"])
        if not isinstance(book, BookBaselinePayload):
            raise ValueError("checkpoint payload has a wrong type")
        checkpoint = BookCheckpoint(
            sequence=int(row["sequence"]),
            session_id=int(row["session_id"]),
            subscription_generation=int(row["subscription_generation"]),
            observed_at_ms=int(row["observed_at_ms"]),
            identity=MarketIdentity(
                condition_id=row["condition_id"],
                market_slug=row["market_slug"],
                token_id=row["token_id"],
            ),
            book=book,
        )
        market = markets.get(checkpoint.identity.condition_id or "")
        snapshot = projected_books.get(checkpoint.book.token_id)
        if market is None:
            raise ValueError("checkpoint has no preceding metadata")
        if snapshot is None:
            raise ValueError("checkpoint has no canonical book state")
        if (
            checkpoint.session_id != session.session_id
            or checkpoint.identity.market_slug != market.market_slug
            or checkpoint.book.token_id
            not in {outcome.token_id for outcome in market.outcomes}
            or checkpoint.observed_at_ms < referenced_event.observed_at_ms
            or checkpoint.observed_at_ms < session.started_at_ms
            or (
                session.ended_at_ms is not None
                and checkpoint.observed_at_ms > session.ended_at_ms
            )
            or generation_by_token.get(checkpoint.book.token_id)
            != checkpoint.subscription_generation
            or {
                (level.price, level.size) for level in checkpoint.book.bids
            }
            != {(level.price, level.size) for level in snapshot.bids}
            or {
                (level.price, level.size) for level in checkpoint.book.asks
            }
            != {(level.price, level.size) for level in snapshot.asks}
            or _has_intervening_state_event(connection, checkpoint)
        ):
            raise ValueError("checkpoint state is inconsistent")
    except (TypeError, ValueError) as error:
        raise RecordingTrimError("trimmed recording checkpoint is malformed") from error


def _has_intervening_state_event(
    connection: sqlite3.Connection,
    checkpoint: BookCheckpoint,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM events AS event
        WHERE event.session_id = ? AND event.condition_id = ?
          AND event.sequence > ? AND event.observed_at_ms < ?
          AND event.payload_kind IN (?, ?, ?, ?, ?, ?)
        LIMIT 1
        """,
        (
            checkpoint.session_id,
            checkpoint.identity.condition_id,
            checkpoint.sequence,
            checkpoint.observed_at_ms,
            PayloadKind.MARKET_METADATA.value,
            PayloadKind.BOOK_BASELINE.value,
            PayloadKind.BOOK_DELTA.value,
            PayloadKind.TICK_SIZE_CHANGE.value,
            PayloadKind.RESOLUTION.value,
            PayloadKind.COVERAGE_GAP.value,
        ),
    ).fetchone()
    return row is not None
