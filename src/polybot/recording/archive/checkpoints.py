"""Book-checkpoint and baseline-pair queries for immutable archive reads."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..contracts.records import BookCheckpoint
from .checkpoint_rows import (
    checkpoint_from_row,
    checkpoint_from_validated_row,
    market_before_checkpoint,
)
from .coverage import reject_known_gaps
from .errors import ArchiveIntegrityError
from .markets import market_at
from .primitives import (
    _nonnegative_timestamp,
    _positive_int,
    _required_text,
    _strict_int,
)


@dataclass(frozen=True, slots=True)
class _CheckpointBoundary:
    observed_at_ms: int
    sequence: int
    session_id: int
    subscription_generation: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> _CheckpointBoundary:
        return cls(
            observed_at_ms=_strict_int(
                row["observed_at_ms"],
                "checkpoint timestamp",
            ),
            sequence=_strict_int(row["sequence"], "checkpoint sequence"),
            session_id=_strict_int(row["session_id"], "checkpoint session"),
            subscription_generation=_strict_int(
                row["subscription_generation"],
                "checkpoint generation",
            ),
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
        SELECT observed_at_ms, sequence, session_id,
               subscription_generation
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
    boundary = _CheckpointBoundary.from_row(row)
    if not allow_gaps:
        reject_known_gaps(
            connection,
            replay_cutoff_sequence=replay_cutoff_sequence,
            start_at_ms=boundary.observed_at_ms,
            end_at_ms=boundary.observed_at_ms,
            session_id=normalized_session,
            condition_ids=(normalized_condition,),
            market_slugs=(market.market_slug,),
            token_id=None,
        )
    return _checkpoint_pair_from_boundary(
        connection,
        normalized_condition,
        token_ids,
        boundary,
        replay_cutoff_sequence=replay_cutoff_sequence,
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
    typed_boundary = _CheckpointBoundary.from_row(boundary)
    if not allow_gaps:
        reject_known_gaps(
            connection,
            replay_cutoff_sequence=replay_cutoff_sequence,
            start_at_ms=typed_boundary.observed_at_ms,
            end_at_ms=observed_at_ms,
            session_id=session_id,
            condition_ids=(condition_id,),
            market_slugs=(market.market_slug,),
            token_id=None,
        )
    return _checkpoint_pair_from_boundary(
        connection,
        condition_id,
        token_ids,
        typed_boundary,
        replay_cutoff_sequence=replay_cutoff_sequence,
    )


def _checkpoint_pair_from_boundary(
    connection: sqlite3.Connection,
    condition_id: str,
    token_ids: tuple[str, str],
    boundary: _CheckpointBoundary,
    *,
    replay_cutoff_sequence: int,
) -> tuple[BookCheckpoint, BookCheckpoint]:
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
            boundary.observed_at_ms,
            boundary.sequence,
            boundary.session_id,
            boundary.subscription_generation,
        ),
    ).fetchall()
    rows_by_token = {row["token_id"]: row for row in rows}
    if set(rows_by_token) != set(token_ids):
        raise ArchiveIntegrityError(
            "common book checkpoint does not contain both market tokens"
        )
    market = market_before_checkpoint(
        connection,
        condition_id,
        boundary.sequence,
    )
    return (
        checkpoint_from_validated_row(
            rows_by_token[token_ids[0]],
            token_ids[0],
            replay_cutoff_sequence=replay_cutoff_sequence,
            market=market,
        ),
        checkpoint_from_validated_row(
            rows_by_token[token_ids[1]],
            token_ids[1],
            replay_cutoff_sequence=replay_cutoff_sequence,
            market=market,
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
