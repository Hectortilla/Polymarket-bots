"""Market metadata revision and resolution-state queries for archives."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import EVENTS_TABLE, METADATA_REVISIONS_TABLE

from ..contracts.book import TickSizeChangePayload
from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketMetadataPayload
from .errors import ArchiveFormatError
from .integrity import _validate_payload_market_identity
from .primitives import _required_text
from .resolutions import apply_recorded_resolution, resolution_event_at
from .rows import _event_from_row, _typed_payload
from .selection import ArchiveSelection


def market_slugs_with_metadata_revisions(
    connection: sqlite3.Connection,
    *,
    replay_cutoff_sequence: int,
    start_at_ms: int,
    end_at_ms: int,
    session_id: int,
    selection: ArchiveSelection,
) -> tuple[str, ...]:
    """Return selected slugs whose metadata changed inside one selection."""

    clauses = [
        f"revision.{ArchiveColumn.OBSERVED_AT_MS} >= ?",
        f"revision.{ArchiveColumn.OBSERVED_AT_MS} <= ?",
        f"revision.{ArchiveColumn.SEQUENCE} <= ?",
        f"metadata_event.{ArchiveColumn.SESSION_ID} = ?",
    ]
    parameters: list[object] = [
        start_at_ms,
        end_at_ms,
        replay_cutoff_sequence,
        session_id,
    ]
    selected_slugs = selection.market_slugs
    if selected_slugs is not None:
        placeholders = ", ".join("?" for _ in selected_slugs)
        clauses.append(
            f"metadata_event.{ArchiveColumn.MARKET_SLUG} IN ({placeholders})"
        )
        parameters.extend(selected_slugs)
    rows = connection.execute(
        f"SELECT DISTINCT metadata_event.{ArchiveColumn.MARKET_SLUG} "
        f"FROM {METADATA_REVISIONS_TABLE} AS revision "
        f"JOIN {EVENTS_TABLE} AS metadata_event "
        f"ON metadata_event.{ArchiveColumn.SEQUENCE} = revision.{ArchiveColumn.SEQUENCE} WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY metadata_event.{ArchiveColumn.MARKET_SLUG}",
        tuple(parameters),
    ).fetchall()
    return tuple(
        _required_text(row[ArchiveColumn.MARKET_SLUG], "metadata revision market slug")
        for row in rows
    )


def markets_at(
    connection: sqlite3.Connection,
    *,
    replay_cutoff_sequence: int,
    observed_at_ms: int,
    selection: ArchiveSelection,
) -> tuple[MarketMetadataPayload, ...]:
    """Enumerate the latest selected metadata revisions at one replay time."""

    clauses = [
        f"revision.{ArchiveColumn.OBSERVED_AT_MS} <= ?",
        f"revision.{ArchiveColumn.SEQUENCE} <= ?",
        f"revision.{ArchiveColumn.SEQUENCE} = ("
        f"SELECT MAX(candidate.{ArchiveColumn.SEQUENCE}) "
        f"FROM {METADATA_REVISIONS_TABLE} AS candidate "
        f"WHERE candidate.{ArchiveColumn.CONDITION_ID} = revision.{ArchiveColumn.CONDITION_ID} "
        f"AND candidate.{ArchiveColumn.OBSERVED_AT_MS} <= ? "
        f"AND candidate.{ArchiveColumn.SEQUENCE} <= ?)",
    ]
    parameters: list[object] = [
        observed_at_ms,
        replay_cutoff_sequence,
        observed_at_ms,
        replay_cutoff_sequence,
    ]
    selected_conditions = selection.condition_ids
    if selected_conditions is not None:
        placeholders = ", ".join("?" for _ in selected_conditions)
        clauses.append(f"revision.{ArchiveColumn.CONDITION_ID} IN ({placeholders})")
        parameters.extend(selected_conditions)
    selected_slugs = selection.market_slugs
    if selected_slugs is not None:
        placeholders = ", ".join("?" for _ in selected_slugs)
        clauses.append(
            f"metadata_event.{ArchiveColumn.MARKET_SLUG} IN ({placeholders})"
        )
        parameters.extend(selected_slugs)
    selected_session = selection.session_id
    if selected_session is not None:
        clauses.append(
            f"EXISTS (SELECT 1 FROM {EVENTS_TABLE} AS participating_event "
            f"WHERE participating_event.{ArchiveColumn.SESSION_ID} = ? "
            f"AND participating_event.{ArchiveColumn.CONDITION_ID} = revision.{ArchiveColumn.CONDITION_ID} "
            f"AND participating_event.{ArchiveColumn.SEQUENCE} <= ?)"
        )
        parameters.extend((selected_session, replay_cutoff_sequence))
    rows = connection.execute(
        f"SELECT revision.{ArchiveColumn.CONDITION_ID}, revision.{ArchiveColumn.PAYLOAD_JSON}, "
        f"metadata_event.{ArchiveColumn.MARKET_SLUG} "
        f"FROM {METADATA_REVISIONS_TABLE} AS revision "
        f"JOIN {EVENTS_TABLE} AS metadata_event "
        f"ON metadata_event.{ArchiveColumn.SEQUENCE} = revision.{ArchiveColumn.SEQUENCE} WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY revision.{ArchiveColumn.CONDITION_ID}",
        tuple(parameters),
    ).fetchall()
    markets: list[MarketMetadataPayload] = []
    for row in rows:
        payload = _typed_payload(
            PayloadKind.MARKET_METADATA,
            row[ArchiveColumn.PAYLOAD_JSON],
            MarketMetadataPayload,
        )
        if (
            payload.condition_id != row[ArchiveColumn.CONDITION_ID]
            or payload.market_slug != row[ArchiveColumn.MARKET_SLUG]
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
        f"""
        SELECT {ArchiveColumn.PAYLOAD_JSON}
        FROM {METADATA_REVISIONS_TABLE}
        WHERE {ArchiveColumn.CONDITION_ID} = ? AND {ArchiveColumn.OBSERVED_AT_MS} <= ? AND {ArchiveColumn.SEQUENCE} <= ?
        ORDER BY {ArchiveColumn.OBSERVED_AT_MS} DESC, {ArchiveColumn.SEQUENCE} DESC
        LIMIT 1
        """,
        (condition_id, observed_at_ms, sequence_cutoff),
    ).fetchone()
    if row is None:
        return None
    payload = _typed_payload(
        PayloadKind.MARKET_METADATA,
        row[ArchiveColumn.PAYLOAD_JSON],
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
        f"""
        SELECT * FROM {EVENTS_TABLE}
        WHERE {ArchiveColumn.CONDITION_ID} = ? AND {ArchiveColumn.PAYLOAD_KIND} IN (?, ?)
          AND {ArchiveColumn.OBSERVED_AT_MS} <= ? AND {ArchiveColumn.SEQUENCE} <= ?
        ORDER BY {ArchiveColumn.OBSERVED_AT_MS} DESC, {ArchiveColumn.SEQUENCE} DESC
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
    if (
        row is None
        or row[ArchiveColumn.PAYLOAD_KIND] == PayloadKind.MARKET_METADATA.value
    ):
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
        query = f"""
        SELECT {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.PAYLOAD_JSON}, {ArchiveColumn.SEQUENCE}
        FROM {METADATA_REVISIONS_TABLE} AS revision
        WHERE {ArchiveColumn.SEQUENCE} <= ?
          AND {ArchiveColumn.SEQUENCE} = (
            SELECT MAX(candidate.{ArchiveColumn.SEQUENCE})
            FROM {METADATA_REVISIONS_TABLE} AS candidate
            WHERE candidate.{ArchiveColumn.CONDITION_ID} = revision.{ArchiveColumn.CONDITION_ID}
              AND candidate.{ArchiveColumn.SEQUENCE} <= ?
        )
        ORDER BY {ArchiveColumn.CONDITION_ID}
        """
        parameters: tuple[object, ...] = (
            replay_cutoff_sequence,
            replay_cutoff_sequence,
        )
    else:
        query = f"""
        SELECT {ArchiveColumn.CONDITION_ID}, {ArchiveColumn.PAYLOAD_JSON}, {ArchiveColumn.SEQUENCE}
        FROM {METADATA_REVISIONS_TABLE} AS revision
        WHERE {ArchiveColumn.OBSERVED_AT_MS} <= ? AND {ArchiveColumn.SEQUENCE} <= ?
          AND {ArchiveColumn.SEQUENCE} = (
            SELECT MAX(candidate.{ArchiveColumn.SEQUENCE})
            FROM {METADATA_REVISIONS_TABLE} AS candidate
            WHERE candidate.{ArchiveColumn.CONDITION_ID} = revision.{ArchiveColumn.CONDITION_ID}
              AND candidate.{ArchiveColumn.OBSERVED_AT_MS} <= ?
              AND candidate.{ArchiveColumn.SEQUENCE} <= ?
          )
        ORDER BY {ArchiveColumn.CONDITION_ID}
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
            row[ArchiveColumn.PAYLOAD_JSON],
            MarketMetadataPayload,
        )
        if payload.resolved:
            continue
        if (
            resolution_event_at(
                connection,
                payload.condition_id,
                sequence_cutoff=replay_cutoff_sequence,
                observed_at_ms=at_ms,
            )
            is None
        ):
            unresolved.append(payload)
    return tuple(unresolved)
