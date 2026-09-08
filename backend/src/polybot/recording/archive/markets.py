"""Market metadata revision and resolution-state queries for archives."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import replace

from ..contracts.book import TickSizeChangePayload
from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketMetadataPayload
from .errors import ArchiveFormatError
from .integrity import _validate_payload_market_identity
from .primitives import _required_text
from .rows import _event_from_row, _typed_payload
from .resolutions import apply_recorded_resolution, resolution_event_at


def market_slugs_with_metadata_revisions(
    connection: sqlite3.Connection,
    *,
    replay_cutoff_sequence: int,
    start_at_ms: int,
    end_at_ms: int,
    session_id: int,
    selection: Mapping[str, object],
) -> tuple[str, ...]:
    """Return selected slugs whose metadata changed inside one selection."""

    clauses = [
        "revision.observed_at_ms >= ?",
        "revision.observed_at_ms <= ?",
        "revision.sequence <= ?",
        "metadata_event.session_id = ?",
    ]
    parameters: list[object] = [
        start_at_ms,
        end_at_ms,
        replay_cutoff_sequence,
        session_id,
    ]
    selected_slugs = selection["market_slugs"]
    if selected_slugs is not None:
        placeholders = ", ".join("?" for _ in selected_slugs)
        clauses.append(f"metadata_event.market_slug IN ({placeholders})")
        parameters.extend(selected_slugs)
    rows = connection.execute(
        "SELECT DISTINCT metadata_event.market_slug "
        "FROM metadata_revisions AS revision "
        "JOIN events AS metadata_event "
        "ON metadata_event.sequence = revision.sequence WHERE "
        + " AND ".join(clauses)
        + " ORDER BY metadata_event.market_slug",
        tuple(parameters),
    ).fetchall()
    return tuple(
        _required_text(row["market_slug"], "metadata revision market slug")
        for row in rows
    )


def markets_at(
    connection: sqlite3.Connection,
    *,
    replay_cutoff_sequence: int,
    observed_at_ms: int,
    selection: Mapping[str, object],
) -> tuple[MarketMetadataPayload, ...]:
    """Enumerate the latest selected metadata revisions at one replay time."""

    clauses = [
        "revision.observed_at_ms <= ?",
        "revision.sequence <= ?",
        "revision.sequence = ("
        "SELECT MAX(candidate.sequence) "
        "FROM metadata_revisions AS candidate "
        "WHERE candidate.condition_id = revision.condition_id "
        "AND candidate.observed_at_ms <= ? "
        "AND candidate.sequence <= ?)",
    ]
    parameters: list[object] = [
        observed_at_ms,
        replay_cutoff_sequence,
        observed_at_ms,
        replay_cutoff_sequence,
    ]
    selected_conditions = selection["condition_ids"]
    if selected_conditions is not None:
        placeholders = ", ".join("?" for _ in selected_conditions)
        clauses.append(f"revision.condition_id IN ({placeholders})")
        parameters.extend(selected_conditions)
    selected_slugs = selection["market_slugs"]
    if selected_slugs is not None:
        placeholders = ", ".join("?" for _ in selected_slugs)
        clauses.append(f"metadata_event.market_slug IN ({placeholders})")
        parameters.extend(selected_slugs)
    selected_session = selection["session_id"]
    if selected_session is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM events AS participating_event "
            "WHERE participating_event.session_id = ? "
            "AND participating_event.condition_id = revision.condition_id "
            "AND participating_event.sequence <= ?)"
        )
        parameters.extend((selected_session, replay_cutoff_sequence))
    rows = connection.execute(
        "SELECT revision.condition_id, revision.payload_json, "
        "metadata_event.market_slug "
        "FROM metadata_revisions AS revision "
        "JOIN events AS metadata_event "
        "ON metadata_event.sequence = revision.sequence WHERE "
        + " AND ".join(clauses)
        + " ORDER BY revision.condition_id",
        tuple(parameters),
    ).fetchall()
    markets: list[MarketMetadataPayload] = []
    for row in rows:
        payload = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row["payload_json"],
            MarketMetadataPayload,
        )
        if (
            payload.condition_id != row["condition_id"]
            or payload.market_slug != row["market_slug"]
        ):
            raise ArchiveFormatError("metadata index identity is inconsistent")
        markets.append(
            apply_recorded_resolution(
                connection,
                payload,
                observed_at_ms=observed_at_ms,
                sequence_cutoff=replay_cutoff_sequence,
            )
        )
    return tuple(markets)


def market_at(
    connection: sqlite3.Connection,
    condition_id: str,
    observed_at_ms: int,
    *,
    sequence_cutoff: int,
) -> MarketMetadataPayload | None:
    """Return time-correct metadata with the latest recorded resolution state."""

    row = connection.execute(
        """
        SELECT payload_json
        FROM metadata_revisions
        WHERE condition_id = ? AND observed_at_ms <= ? AND sequence <= ?
        ORDER BY observed_at_ms DESC, sequence DESC
        LIMIT 1
        """,
        (condition_id, observed_at_ms, sequence_cutoff),
    ).fetchone()
    if row is None:
        return None
    payload = _typed_payload(
        PayloadKind.MARKET_METADATA,
        row["payload_json"],
        MarketMetadataPayload,
    )
    if payload.condition_id != condition_id:
        raise ArchiveFormatError("metadata index identity is inconsistent")
    return apply_recorded_resolution(
        connection,
        payload,
        observed_at_ms=observed_at_ms,
        sequence_cutoff=sequence_cutoff,
    )


def market_state_at(
    connection: sqlite3.Connection,
    condition_id: str,
    observed_at_ms: int,
    *,
    sequence_cutoff: int,
) -> MarketMetadataPayload | None:
    """Return metadata plus the latest ordered tick and resolution state."""

    market = market_at(
        connection,
        condition_id,
        observed_at_ms,
        sequence_cutoff=sequence_cutoff,
    )
    if market is None:
        return None
    row = connection.execute(
        """
        SELECT * FROM events
        WHERE condition_id = ? AND payload_kind IN (?, ?)
          AND observed_at_ms <= ? AND sequence <= ?
        ORDER BY observed_at_ms DESC, sequence DESC
        LIMIT 1
        """,
        (
            condition_id,
            PayloadKind.MARKET_METADATA.value,
            PayloadKind.TICK_SIZE_CHANGE.value,
            observed_at_ms,
            sequence_cutoff,
        ),
    ).fetchone()
    if row is None or row["payload_kind"] == PayloadKind.MARKET_METADATA.value:
        return market
    event = _event_from_row(row)
    if not isinstance(event.payload, TickSizeChangePayload):
        raise ArchiveFormatError("tick-size state index contains a wrong payload")
    _validate_payload_market_identity(event, market)
    return replace(market, minimum_tick_size=event.payload.new_tick_size)


def unresolved_markets(
    connection: sqlite3.Connection,
    *,
    replay_cutoff_sequence: int,
    at_ms: int | None,
) -> tuple[MarketMetadataPayload, ...]:
    """Return latest metadata for markets unresolved at the requested time."""

    if at_ms is None:
        query = """
        SELECT condition_id, payload_json, sequence
        FROM metadata_revisions AS revision
        WHERE sequence <= ?
          AND sequence = (
            SELECT MAX(candidate.sequence)
            FROM metadata_revisions AS candidate
            WHERE candidate.condition_id = revision.condition_id
              AND candidate.sequence <= ?
        )
        ORDER BY condition_id
        """
        parameters: tuple[object, ...] = (
            replay_cutoff_sequence,
            replay_cutoff_sequence,
        )
    else:
        query = """
        SELECT condition_id, payload_json, sequence
        FROM metadata_revisions AS revision
        WHERE observed_at_ms <= ? AND sequence <= ?
          AND sequence = (
            SELECT MAX(candidate.sequence)
            FROM metadata_revisions AS candidate
            WHERE candidate.condition_id = revision.condition_id
              AND candidate.observed_at_ms <= ?
              AND candidate.sequence <= ?
          )
        ORDER BY condition_id
        """
        parameters = (
            at_ms,
            replay_cutoff_sequence,
            at_ms,
            replay_cutoff_sequence,
        )
    rows = connection.execute(query, parameters).fetchall()
    unresolved: list[MarketMetadataPayload] = []
    for row in rows:
        payload = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row["payload_json"],
            MarketMetadataPayload,
        )
        if payload.resolved:
            continue
        if resolution_event_at(
            connection,
            payload.condition_id,
            sequence_cutoff=replay_cutoff_sequence,
            observed_at_ms=at_ms,
        ) is None:
            unresolved.append(payload)
    return tuple(unresolved)
