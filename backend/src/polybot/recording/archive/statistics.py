"""Typed aggregate queries for immutable recording reader snapshots."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from .errors import ArchiveFormatError
from .schema import CAPTURE_ANOMALIES_TABLE
from .models import (
    RecordingEventBounds,
    RecordingEventCounts,
    RecordingFeatureProvenance,
    RecordingMarketStatistics,
    RecordingSession,
    RecordingSessionStatistics,
)
from ..contracts.kinds import PayloadKind


def read_recording_statistics(
    connection: sqlite3.Connection,
    *,
    sessions: tuple[RecordingSession, ...],
    replay_cutoff_sequence: int,
    anomaly_cutoff_id: int,
    anomaly_provenance: RecordingFeatureProvenance | None,
) -> tuple[RecordingSessionStatistics, ...]:
    grouped_rows = connection.execute(
        """
        SELECT session_id, condition_id, market_slug, payload_kind,
               COUNT(*) AS event_count,
               MIN(observed_at_ms) AS start_at_ms,
               MAX(observed_at_ms) AS end_at_ms,
               MIN(sequence) AS first_sequence,
               MAX(sequence) AS last_sequence
        FROM events
        WHERE sequence <= ?
        GROUP BY session_id, condition_id, market_slug, payload_kind
        ORDER BY session_id, condition_id, market_slug, payload_kind
        """,
        (replay_cutoff_sequence,),
    ).fetchall()
    checkpoint_rows = connection.execute(
        """
        SELECT session_id, COUNT(*) AS checkpoint_count
        FROM book_checkpoints
        WHERE sequence <= ?
        GROUP BY session_id
        """,
        (replay_cutoff_sequence,),
    ).fetchall()
    anomaly_rows = (
        ()
        if anomaly_provenance is None
        else connection.execute(
            f"""
            SELECT session_id, COUNT(*) AS anomaly_count
            FROM {CAPTURE_ANOMALIES_TABLE}
            WHERE anomaly_id <= ?
            GROUP BY session_id
            """,
            (anomaly_cutoff_id,),
        ).fetchall()
    )
    return _statistics_from_rows(
        sessions=sessions,
        grouped_rows=grouped_rows,
        checkpoint_rows=checkpoint_rows,
        anomaly_rows=anomaly_rows,
        anomaly_provenance=anomaly_provenance,
    )


def _statistics_from_rows(
    *,
    sessions: tuple[RecordingSession, ...],
    grouped_rows: Iterable[sqlite3.Row],
    checkpoint_rows: Iterable[sqlite3.Row],
    anomaly_rows: Iterable[sqlite3.Row],
    anomaly_provenance: RecordingFeatureProvenance | None,
) -> tuple[RecordingSessionStatistics, ...]:
    session_ids = {session.session_id for session in sessions}
    counts_by_session = {
        session_id: {kind.event_count_field: 0 for kind in PayloadKind}
        for session_id in session_ids
    }
    bounds_by_session: dict[int, list[int] | None] = {
        session_id: None for session_id in session_ids
    }
    market_rows: dict[tuple[int, str, str], list[int]] = {}

    try:
        for row in grouped_rows:
            session_id = _integer(row["session_id"], "statistics session ID", 1)
            _require_session(session_id, session_ids)
            kind = PayloadKind(row["payload_kind"])
            event_count = _integer(row["event_count"], "event count", 1)
            start_at_ms = _integer(
                row["start_at_ms"],
                "event statistics start",
                0,
            )
            end_at_ms = _integer(row["end_at_ms"], "event statistics end", 0)
            first_sequence = _integer(
                row["first_sequence"],
                "event statistics first sequence",
                1,
            )
            last_sequence = _integer(
                row["last_sequence"],
                "event statistics last sequence",
                1,
            )
            counts_by_session[session_id][kind.event_count_field] += event_count
            if kind is PayloadKind.COVERAGE_GAP:
                continue
            _merge_bounds(
                bounds_by_session,
                session_id=session_id,
                first_sequence=first_sequence,
                last_sequence=last_sequence,
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
            )
            condition_id = row["condition_id"]
            market_slug = row["market_slug"]
            if condition_id is not None and market_slug is not None:
                _merge_market(
                    market_rows,
                    key=(session_id, _text(condition_id), _text(market_slug)),
                    event_count=event_count,
                    start_at_ms=start_at_ms,
                    end_at_ms=end_at_ms,
                )
    except (KeyError, TypeError, ValueError) as error:
        raise ArchiveFormatError("recording statistics are malformed") from error

    checkpoints_by_session = _grouped_count_rows(
        checkpoint_rows,
        session_ids=session_ids,
        count_column="checkpoint_count",
    )
    anomalies_by_session = _grouped_count_rows(
        anomaly_rows,
        session_ids=session_ids,
        count_column="anomaly_count",
    )
    return tuple(
        _session_statistics(
            session,
            raw_bounds=bounds_by_session[session.session_id],
            raw_counts=counts_by_session[session.session_id],
            market_rows=market_rows,
            checkpoint_count=checkpoints_by_session.get(session.session_id, 0),
            anomaly_count=(
                None
                if anomaly_provenance is None
                or session.session_id < anomaly_provenance.available_from_session_id
                else anomalies_by_session.get(session.session_id, 0)
            ),
        )
        for session in sessions
    )


def _merge_bounds(
    bounds_by_session: dict[int, list[int] | None],
    *,
    session_id: int,
    first_sequence: int,
    last_sequence: int,
    start_at_ms: int,
    end_at_ms: int,
) -> None:
    bounds = bounds_by_session[session_id]
    if bounds is None:
        bounds_by_session[session_id] = [
            first_sequence,
            last_sequence,
            start_at_ms,
            end_at_ms,
        ]
        return
    bounds[0] = min(bounds[0], first_sequence)
    bounds[1] = max(bounds[1], last_sequence)
    bounds[2] = min(bounds[2], start_at_ms)
    bounds[3] = max(bounds[3], end_at_ms)


def _merge_market(
    market_rows: dict[tuple[int, str, str], list[int]],
    *,
    key: tuple[int, str, str],
    event_count: int,
    start_at_ms: int,
    end_at_ms: int,
) -> None:
    market = market_rows.get(key)
    if market is None:
        market_rows[key] = [event_count, start_at_ms, end_at_ms]
        return
    market[0] += event_count
    market[1] = min(market[1], start_at_ms)
    market[2] = max(market[2], end_at_ms)


def _session_statistics(
    session: RecordingSession,
    *,
    raw_bounds: list[int] | None,
    raw_counts: dict[str, int],
    market_rows: dict[tuple[int, str, str], list[int]],
    checkpoint_count: int,
    anomaly_count: int | None,
) -> RecordingSessionStatistics:
    bounds = (
        None
        if raw_bounds is None
        else RecordingEventBounds(
            first_sequence=raw_bounds[0],
            last_sequence=raw_bounds[1],
            start_at_ms=raw_bounds[2],
            end_at_ms=raw_bounds[3],
        )
    )
    markets = tuple(
        RecordingMarketStatistics(
            condition_id=condition_id,
            market_slug=market_slug,
            event_count=values[0],
            start_at_ms=values[1],
            end_at_ms=values[2],
        )
        for (session_id, condition_id, market_slug), values in market_rows.items()
        if session_id == session.session_id
    )
    return RecordingSessionStatistics(
        session=session,
        event_bounds=bounds,
        event_counts=RecordingEventCounts(**raw_counts),
        checkpoint_count=checkpoint_count,
        capture_anomaly_count=anomaly_count,
        markets=tuple(
            sorted(
                markets,
                key=lambda market: (
                    market.start_at_ms,
                    market.market_slug,
                    market.condition_id,
                ),
            )
        ),
    )


def _grouped_count_rows(
    rows: Iterable[sqlite3.Row],
    *,
    session_ids: set[int],
    count_column: str,
) -> dict[int, int]:
    result: dict[int, int] = {}
    try:
        for row in rows:
            session_id = _integer(row["session_id"], "statistics session ID", 1)
            _require_session(session_id, session_ids)
            result[session_id] = _integer(
                row[count_column],
                count_column.replace("_", " "),
                0,
            )
    except (KeyError, TypeError, ValueError) as error:
        raise ArchiveFormatError("recording statistics are malformed") from error
    return result


def _require_session(session_id: int, session_ids: set[int]) -> None:
    if session_id not in session_ids:
        raise ValueError("recording statistics reference an unknown session")


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} is invalid")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("recording statistics market identity is invalid")
    return value.strip()
