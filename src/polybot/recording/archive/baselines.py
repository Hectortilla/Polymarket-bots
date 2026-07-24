"""Baseline-availability queries for immutable archive reads."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketMetadataPayload
from .primitives import _nonnegative_int, _nonnegative_timestamp, _positive_int


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
