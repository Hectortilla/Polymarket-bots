"""Book-checkpoint and baseline-pair queries for immutable archive reads."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from ..contracts.book import BookBaselinePayload
from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketIdentity, MarketMetadataPayload
from ..contracts.records import BookCheckpoint
from .coverage import reject_known_gaps
from .errors import ArchiveFormatError, ArchiveIntegrityError
from .markets import market_at
from .primitives import (
    _nonnegative_int,
    _nonnegative_timestamp,
    _positive_int,
    _required_text,
    _strict_int,
)
from .rows import _typed_payload


def has_complete_baseline_pair(
    connection: sqlite3.Connection,
    market: MarketMetadataPayload,
    *,
    replay_cutoff_sequence: int,
    start_at_ms: int,
    end_at_ms: int,
    session_id: int | None = None,
    after_sequence_by_token: Mapping[str, int] | None = None,
) -> bool:
    """Return whether one generation baselines both market tokens in-range."""

    return (
        first_complete_baseline_pair_at_or_after(
            connection,
            market,
            replay_cutoff_sequence=replay_cutoff_sequence,
            start_at_ms=start_at_ms,
            end_at_ms=end_at_ms,
            session_id=session_id,
            after_sequence_by_token=after_sequence_by_token,
        )
        is not None
    )


def first_complete_baseline_pair_at_or_after(
    connection: sqlite3.Connection,
    market: MarketMetadataPayload,
    *,
    replay_cutoff_sequence: int,
    start_at_ms: int,
    end_at_ms: int,
    session_id: int | None = None,
    after_sequence_by_token: Mapping[str, int] | None = None,
) -> int | None:
    """Return the first in-range timestamp with both baseline tokens present."""

    if not isinstance(market, MarketMetadataPayload):
        raise ValueError("baseline-pair market metadata is invalid")
    _nonnegative_timestamp(start_at_ms, "baseline-pair start")
    _nonnegative_timestamp(end_at_ms, "baseline-pair end")
    if end_at_ms < start_at_ms:
        raise ValueError("baseline-pair selection cannot end before it starts")
    normalized_session = (
        None if session_id is None else _positive_int(session_id, "session ID")
    )
    token_ids = tuple(outcome.token_id for outcome in market.outcomes)
    unknown_tokens = set(after_sequence_by_token or ()).difference(token_ids)
    if unknown_tokens:
        raise ValueError("baseline sequence cutoffs contain an unknown token")
    sequence_cutoffs = tuple(
        _nonnegative_int(
            0
            if after_sequence_by_token is None
            else after_sequence_by_token.get(token_id, 0),
            "baseline sequence cutoff",
        )
        for token_id in token_ids
    )
    session_clause = "" if normalized_session is None else "AND event.session_id = ?"
    parameters: list[object] = [
        PayloadKind.BOOK_BASELINE.value,
        market.condition_id,
        start_at_ms,
        end_at_ms,
        replay_cutoff_sequence,
        *token_ids,
        token_ids[0],
        sequence_cutoffs[0],
        token_ids[1],
        sequence_cutoffs[1],
    ]
    if normalized_session is not None:
        parameters.append(normalized_session)
    row = connection.execute(
        f"""
        WITH first_token_baseline AS (
            SELECT event.subscription_generation,
                   selected_token.token_id,
                   MIN(event.observed_at_ms) AS first_observed_at_ms
            FROM events AS event
            JOIN event_tokens AS selected_token
              ON selected_token.sequence = event.sequence
            WHERE event.payload_kind = ? AND event.condition_id = ?
              AND event.observed_at_ms >= ?
              AND event.observed_at_ms <= ?
              AND event.sequence <= ?
              AND selected_token.token_id IN (?, ?)
              AND (
                  (selected_token.token_id = ? AND event.sequence > ?)
                  OR
                  (selected_token.token_id = ? AND event.sequence > ?)
              )
              {session_clause}
            GROUP BY event.subscription_generation,
                     selected_token.token_id
        )
        SELECT MAX(first_observed_at_ms) AS complete_at_ms
        FROM first_token_baseline
        GROUP BY subscription_generation
        HAVING COUNT(DISTINCT token_id) = 2
        ORDER BY complete_at_ms
        LIMIT 1
        """,
        tuple(parameters),
    ).fetchone()
    return (
        None
        if row is None
        else _nonnegative_int(
            row["complete_at_ms"],
            "complete baseline-pair timestamp",
        )
    )


def checkpoint_before(
    connection: sqlite3.Connection,
    token_id: str,
    observed_at_ms: int,
    *,
    replay_cutoff_sequence: int,
    session_id: int | None = None,
    allow_gaps: bool = False,
) -> BookCheckpoint | None:
    """Return the newest token checkpoint at or before one observation time."""

    normalized_token = _required_text(token_id, "token ID")
    _nonnegative_timestamp(observed_at_ms, "checkpoint lookup timestamp")
    normalized_session = (
        None if session_id is None else _positive_int(session_id, "session ID")
    )
    session_clause = "" if normalized_session is None else "AND session_id = ?"
    parameters: list[object] = [
        normalized_token,
        observed_at_ms,
        replay_cutoff_sequence,
    ]
    if normalized_session is not None:
        parameters.append(normalized_session)
    row = connection.execute(
        f"""
        SELECT *
        FROM book_checkpoints
        WHERE token_id = ? AND observed_at_ms <= ? AND sequence <= ?
          {session_clause}
        ORDER BY observed_at_ms DESC, sequence DESC
        LIMIT 1
        """,
        tuple(parameters),
    ).fetchone()
    if row is None:
        return None
    if not allow_gaps:
        reject_known_gaps(
            connection,
            replay_cutoff_sequence=replay_cutoff_sequence,
            start_at_ms=int(row["observed_at_ms"]),
            end_at_ms=observed_at_ms,
            session_id=normalized_session,
            condition_ids=(row["condition_id"],),
            market_slugs=(row["market_slug"],),
            token_id=normalized_token,
        )
    return checkpoint_from_row(
        connection,
        row,
        normalized_token,
        replay_cutoff_sequence=replay_cutoff_sequence,
    )


def checkpoint_pair_before(
    connection: sqlite3.Connection,
    condition_id: str,
    observed_at_ms: int,
    *,
    replay_cutoff_sequence: int,
    session_id: int | None = None,
    allow_gaps: bool = False,
) -> tuple[BookCheckpoint, BookCheckpoint] | None:
    """Return the newest same-boundary checkpoint pair for one market."""

    normalized_condition = _required_text(condition_id, "condition ID")
    _nonnegative_timestamp(observed_at_ms, "checkpoint lookup timestamp")
    normalized_session = (
        None if session_id is None else _positive_int(session_id, "session ID")
    )
    return _checkpoint_pair_before(
        connection,
        normalized_condition,
        observed_at_ms,
        replay_cutoff_sequence=replay_cutoff_sequence,
        session_id=normalized_session,
        allow_gaps=allow_gaps,
    )


def checkpoint_pair_at(
    connection: sqlite3.Connection,
    condition_id: str,
    observed_at_ms: int,
    *,
    replay_cutoff_sequence: int,
    session_id: int | None = None,
    allow_gaps: bool = False,
) -> tuple[BookCheckpoint, BookCheckpoint] | None:
    """Return a same-boundary checkpoint pair exactly at one observation time."""

    normalized_condition = _required_text(condition_id, "condition ID")
    _nonnegative_timestamp(observed_at_ms, "checkpoint lookup timestamp")
    normalized_session = (
        None if session_id is None else _positive_int(session_id, "session ID")
    )
    return _checkpoint_pair_at(
        connection,
        normalized_condition,
        observed_at_ms,
        replay_cutoff_sequence=replay_cutoff_sequence,
        session_id=normalized_session,
        allow_gaps=allow_gaps,
    )


def checkpoint_pair_at_or_after(
    connection: sqlite3.Connection,
    condition_id: str,
    observed_at_ms: int,
    *,
    replay_cutoff_sequence: int,
    end_at_ms: int,
    session_id: int | None = None,
    allow_gaps: bool = False,
) -> tuple[BookCheckpoint, BookCheckpoint] | None:
    """Return the first same-boundary checkpoint pair in an inclusive range."""

    normalized_condition = _required_text(condition_id, "condition ID")
    _nonnegative_timestamp(observed_at_ms, "checkpoint lookup timestamp")
    _nonnegative_timestamp(end_at_ms, "checkpoint lookup end")
    if end_at_ms < observed_at_ms:
        raise ValueError("checkpoint lookup end cannot precede its start")
    normalized_session = (
        None if session_id is None else _positive_int(session_id, "session ID")
    )
    market = market_at(
        connection,
        normalized_condition,
        end_at_ms,
        sequence_cutoff=replay_cutoff_sequence,
    )
    if market is None:
        return None
    token_ids = tuple(outcome.token_id for outcome in market.outcomes)
    session_clause = "" if normalized_session is None else "AND session_id = ?"
    parameters: list[object] = [
        normalized_condition,
        *token_ids,
        observed_at_ms,
        end_at_ms,
        replay_cutoff_sequence,
    ]
    if normalized_session is not None:
        parameters.append(normalized_session)
    row = connection.execute(
        f"""
        SELECT observed_at_ms
        FROM book_checkpoints
        WHERE condition_id = ? AND token_id IN (?, ?)
          AND observed_at_ms >= ? AND observed_at_ms <= ?
          AND sequence <= ? {session_clause}
        GROUP BY observed_at_ms, sequence, session_id,
                 subscription_generation
        HAVING COUNT(DISTINCT token_id) = 2
        ORDER BY observed_at_ms, sequence
        LIMIT 1
        """,
        tuple(parameters),
    ).fetchone()
    if row is None:
        return None
    boundary_ms = _strict_int(row["observed_at_ms"], "checkpoint timestamp")
    return _checkpoint_pair_at(
        connection,
        normalized_condition,
        boundary_ms,
        replay_cutoff_sequence=replay_cutoff_sequence,
        session_id=normalized_session,
        allow_gaps=allow_gaps,
    )


def _checkpoint_pair_before(
    connection: sqlite3.Connection,
    condition_id: str,
    observed_at_ms: int,
    *,
    replay_cutoff_sequence: int,
    session_id: int | None,
    allow_gaps: bool,
) -> tuple[BookCheckpoint, BookCheckpoint] | None:
    market = market_at(
        connection,
        condition_id,
        observed_at_ms,
        sequence_cutoff=replay_cutoff_sequence,
    )
    if market is None:
        return None
    token_ids = tuple(outcome.token_id for outcome in market.outcomes)
    session_clause = "" if session_id is None else "AND session_id = ?"
    parameters: list[object] = [
        condition_id,
        *token_ids,
        observed_at_ms,
        replay_cutoff_sequence,
    ]
    if session_id is not None:
        parameters.append(session_id)
    boundary = connection.execute(
        f"""
        SELECT observed_at_ms, sequence, session_id,
               subscription_generation
        FROM book_checkpoints
        WHERE condition_id = ? AND token_id IN (?, ?)
          AND observed_at_ms <= ? AND sequence <= ?
          {session_clause}
        GROUP BY observed_at_ms, sequence, session_id,
                 subscription_generation
        HAVING COUNT(DISTINCT token_id) = 2
        ORDER BY observed_at_ms DESC, sequence DESC
        LIMIT 1
        """,
        tuple(parameters),
    ).fetchone()
    if boundary is None:
        return None
    if not allow_gaps:
        reject_known_gaps(
            connection,
            replay_cutoff_sequence=replay_cutoff_sequence,
            start_at_ms=_strict_int(
                boundary["observed_at_ms"],
                "checkpoint timestamp",
            ),
            end_at_ms=observed_at_ms,
            session_id=session_id,
            condition_ids=(condition_id,),
            market_slugs=(market.market_slug,),
            token_id=None,
        )
    rows = connection.execute(
        """
        SELECT * FROM book_checkpoints
        WHERE condition_id = ? AND token_id IN (?, ?)
          AND observed_at_ms = ? AND sequence = ? AND session_id = ?
          AND subscription_generation = ?
        """,
        (
            condition_id,
            *token_ids,
            boundary["observed_at_ms"],
            boundary["sequence"],
            boundary["session_id"],
            boundary["subscription_generation"],
        ),
    ).fetchall()
    rows_by_token = {row["token_id"]: row for row in rows}
    if set(rows_by_token) != set(token_ids):
        raise ArchiveIntegrityError(
            "common book checkpoint does not contain both market tokens"
        )
    return (
        checkpoint_from_row(
            connection,
            rows_by_token[token_ids[0]],
            token_ids[0],
            replay_cutoff_sequence=replay_cutoff_sequence,
        ),
        checkpoint_from_row(
            connection,
            rows_by_token[token_ids[1]],
            token_ids[1],
            replay_cutoff_sequence=replay_cutoff_sequence,
        ),
    )


def _checkpoint_pair_at(
    connection: sqlite3.Connection,
    condition_id: str,
    observed_at_ms: int,
    *,
    replay_cutoff_sequence: int,
    session_id: int | None,
    allow_gaps: bool,
) -> tuple[BookCheckpoint, BookCheckpoint] | None:
    checkpoints = _checkpoint_pair_before(
        connection,
        condition_id,
        observed_at_ms,
        replay_cutoff_sequence=replay_cutoff_sequence,
        session_id=session_id,
        allow_gaps=True,
    )
    if checkpoints is None or checkpoints[0].observed_at_ms != observed_at_ms:
        return None
    if not allow_gaps:
        reject_known_gaps(
            connection,
            replay_cutoff_sequence=replay_cutoff_sequence,
            start_at_ms=observed_at_ms,
            end_at_ms=observed_at_ms,
            session_id=session_id,
            condition_ids=(condition_id,),
            market_slugs=(checkpoints[0].identity.market_slug or "",),
            token_id=None,
        )
    return checkpoints


def checkpoint_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    token_id: str,
    *,
    replay_cutoff_sequence: int,
) -> BookCheckpoint:
    """Decode and validate a checkpoint row against its prior metadata."""

    sequence = _strict_int(row["sequence"], "checkpoint sequence")
    if sequence > replay_cutoff_sequence:
        raise ArchiveIntegrityError("book checkpoint exceeds the replay cutoff")
    book = _typed_payload(
        PayloadKind.BOOK_BASELINE,
        row["payload_json"],
        BookBaselinePayload,
    )
    metadata_row = connection.execute(
        """
        SELECT payload_json FROM metadata_revisions
        WHERE condition_id = ? AND sequence <= ?
        ORDER BY sequence DESC
        LIMIT 1
        """,
        (row["condition_id"], sequence),
    ).fetchone()
    if metadata_row is None:
        raise ArchiveIntegrityError("book checkpoint has no preceding market metadata")
    market = _typed_payload(
        PayloadKind.MARKET_METADATA,
        metadata_row["payload_json"],
        MarketMetadataPayload,
    )
    if (
        row["condition_id"] != market.condition_id
        or row["market_slug"] != market.market_slug
        or token_id not in {outcome.token_id for outcome in market.outcomes}
        or book.token_id != token_id
    ):
        raise ArchiveIntegrityError(
            "book checkpoint identity does not match market metadata"
        )
    try:
        return BookCheckpoint(
            sequence=sequence,
            session_id=_strict_int(row["session_id"], "checkpoint session"),
            subscription_generation=_strict_int(
                row["subscription_generation"],
                "checkpoint generation",
            ),
            observed_at_ms=_strict_int(
                row["observed_at_ms"],
                "checkpoint timestamp",
            ),
            identity=MarketIdentity(
                condition_id=row["condition_id"],
                market_slug=row["market_slug"],
                token_id=token_id,
            ),
            book=book,
        )
    except ValueError as error:
        raise ArchiveFormatError("book checkpoint is malformed") from error
