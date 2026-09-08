"""Recorded resolution lookup and application for archive market state."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from polybot.polymarket.resolution_status import ResolutionStatus

from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketMetadataPayload
from ..contracts.payloads import ResolutionPayload
from ..contracts.records import RecordedEvent
from .errors import ArchiveFormatError
from .integrity import _validate_payload_market_identity
from .rows import _event_from_row


def resolution_event_at(
    connection: sqlite3.Connection,
    condition_id: str,
    *,
    sequence_cutoff: int,
    observed_at_ms: int | None,
) -> RecordedEvent | None:
    time_clause = "" if observed_at_ms is None else "AND observed_at_ms <= ?"
    parameters: list[object] = [
        condition_id,
        PayloadKind.RESOLUTION.value,
        sequence_cutoff,
    ]
    if observed_at_ms is not None:
        parameters.append(observed_at_ms)
    row = connection.execute(
        f"""
        SELECT * FROM events
        WHERE condition_id = ? AND payload_kind = ? AND sequence <= ?
          {time_clause}
        ORDER BY observed_at_ms DESC, sequence DESC
        LIMIT 1
        """,
        tuple(parameters),
    ).fetchone()
    if row is None:
        return None
    event = _event_from_row(row)
    if not isinstance(event.payload, ResolutionPayload):
        raise ArchiveFormatError("resolution index contains a wrong payload")
    return event


def apply_recorded_resolution(
    connection: sqlite3.Connection,
    market: MarketMetadataPayload,
    *,
    observed_at_ms: int,
    sequence_cutoff: int,
) -> MarketMetadataPayload:
    event = resolution_event_at(
        connection,
        market.condition_id,
        sequence_cutoff=sequence_cutoff,
        observed_at_ms=observed_at_ms,
    )
    if event is None:
        return market
    payload = event.payload
    if not isinstance(payload, ResolutionPayload):
        raise AssertionError("resolution lookup returned a wrong payload")
    _validate_payload_market_identity(event, market)
    return replace(
        market,
        resolution_status=(
            market.resolution_status
            if market.resolved
            else ResolutionStatus.RESOLVED
        ),
        resolution_source=market.resolution_source or payload.source,
        resolved=True,
        winning_token_id=payload.winning_token_id,
        winning_outcome=payload.winning_outcome,
    )
