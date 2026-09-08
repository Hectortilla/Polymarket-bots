"""Replay-event queries for immutable recording archive snapshots."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from polybot.recording.archive.columns import ArchiveColumn

from ..contracts.gaps import CoverageGapPayload
from ..contracts.kinds import PayloadKind
from ..contracts.market import MarketMetadataPayload
from ..contracts.records import RecordedEvent
from .coverage import reject_known_gaps
from .errors import ArchiveIntegrityError
from .integrity import _validate_stored_event_dependencies
from .lifecycle import _open_readonly_connection
from .models import RecordingEventBounds
from .primitives import _nonnegative_int, _strict_int
from .rows import _event_from_row
from .selection import ArchiveSelection, _event_query, _gap_affects


def stream_events(
    *,
    path: Path,
    immutable: bool,
    replay_cutoff_sequence: int,
    selection: ArchiveSelection,
    allow_gaps: bool,
) -> Iterator[RecordedEvent]:
    """Stream validated canonical events from one immutable selection."""

    connection, query, parameters = _prepare_event_query(
        path,
        immutable=immutable,
        replay_cutoff_sequence=replay_cutoff_sequence,
        selection=selection,
        allow_gaps=allow_gaps,
    )
    try:
        cursor = connection.execute(query, parameters)
    except BaseException:
        connection.close()
        raise

    def iterate() -> Iterator[RecordedEvent]:
        verified_metadata: dict[str, MarketMetadataPayload] = {}
        verified_baselines: set[tuple[int, int, str]] = set()
        try:
            for row in cursor:
                event = _event_from_row(row)
                if isinstance(event.payload, CoverageGapPayload) and (
                    event.payload.is_instantaneous
                    or not _gap_affects(
                        event.identity,
                        event.payload,
                        condition_ids=selection.condition_ids,
                        market_slugs=selection.market_slugs,
                        token_id=selection.token_id,
                    )
                ):
                    continue
                _validate_stored_event_dependencies(
                    connection,
                    event,
                    verified_metadata,
                    verified_baselines,
                )
                yield event
        finally:
            connection.close()

    return iterate()


def event_bounds(
    *,
    path: Path,
    immutable: bool,
    replay_cutoff_sequence: int,
    selection: ArchiveSelection,
    allow_gaps: bool,
) -> RecordingEventBounds | None:
    """Return non-gap event bounds for one validated immutable selection."""

    connection, query, parameters = _prepare_event_query(
        path,
        immutable=immutable,
        replay_cutoff_sequence=replay_cutoff_sequence,
        selection=selection,
        allow_gaps=allow_gaps,
        ordered=False,
    )
    try:
        boundary_query = (
            f"SELECT {ArchiveColumn.SEQUENCE}, {ArchiveColumn.OBSERVED_AT_MS} FROM ("
            + query
            + f") AS selected_event WHERE {ArchiveColumn.PAYLOAD_KIND} != ? "
            f"ORDER BY {ArchiveColumn.SEQUENCE} {{}} LIMIT 1"
        )
        boundary_parameters = (*parameters, PayloadKind.COVERAGE_GAP.value)
        first = connection.execute(
            boundary_query.format("ASC"),
            boundary_parameters,
        ).fetchone()
        if first is None:
            return None
        last = connection.execute(
            boundary_query.format("DESC"),
            boundary_parameters,
        ).fetchone()
        if last is None:
            raise ArchiveIntegrityError("recording event bounds are inconsistent")
        return RecordingEventBounds(
            first_sequence=_strict_int(
                first[ArchiveColumn.SEQUENCE], "first event sequence"
            ),
            last_sequence=_strict_int(
                last[ArchiveColumn.SEQUENCE], "last event sequence"
            ),
            start_at_ms=_strict_int(
                first[ArchiveColumn.OBSERVED_AT_MS], "first event timestamp"
            ),
            end_at_ms=_strict_int(
                last[ArchiveColumn.OBSERVED_AT_MS], "last event timestamp"
            ),
        )
    finally:
        connection.close()


def event_count(
    *,
    path: Path,
    immutable: bool,
    replay_cutoff_sequence: int,
    selection: ArchiveSelection,
    allow_gaps: bool,
) -> int:
    """Count non-gap canonical events in one validated immutable selection."""

    connection, query, parameters = _prepare_event_query(
        path,
        immutable=immutable,
        replay_cutoff_sequence=replay_cutoff_sequence,
        selection=selection,
        allow_gaps=allow_gaps,
        ordered=False,
    )
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM ("
            + query
            + f") AS selected_event WHERE {ArchiveColumn.PAYLOAD_KIND} != ?",
            (*parameters, PayloadKind.COVERAGE_GAP.value),
        ).fetchone()
        if row is None:
            raise ArchiveIntegrityError("recording event count is unavailable")
        return _nonnegative_int(row[0], "recording event count")
    finally:
        connection.close()


def _prepare_event_query(
    path: Path,
    *,
    immutable: bool,
    replay_cutoff_sequence: int,
    selection: ArchiveSelection,
    allow_gaps: bool,
    ordered: bool = True,
) -> tuple[sqlite3.Connection, str, tuple[object, ...]]:
    connection = _open_readonly_connection(path, immutable=immutable)
    try:
        connection.execute("BEGIN")
        if not allow_gaps:
            reject_known_gaps(
                connection,
                replay_cutoff_sequence=replay_cutoff_sequence,
                start_at_ms=selection.start_at_ms,
                end_at_ms=selection.end_at_ms,
                session_id=selection.session_id,
                condition_ids=selection.condition_ids,
                market_slugs=selection.market_slugs,
                token_id=selection.token_id,
            )
        query, parameters = _event_query(
            selection,
            replay_cutoff_sequence=replay_cutoff_sequence,
            ordered=ordered,
        )
        return connection, query, parameters
    except BaseException:
        connection.close()
        raise
