"""Coverage-gap queries and replay-safety validation for archive reads."""

from __future__ import annotations

import sqlite3

from polybot.recording.archive.columns import ArchiveColumn
from polybot.recording.archive.schema import COVERAGE_GAPS_TABLE

from ..contracts.gaps import CoverageGapPayload
from ..contracts.kinds import PayloadKind
from ..contracts.records import CoverageGapRecord
from .errors import ArchiveCoverageError, ArchiveFormatError
from .primitives import _strict_int
from .rows import _identity_from_row, _typed_payload
from .selection import _gap_affects


def coverage_gaps(
    connection: sqlite3.Connection,
    *,
    replay_cutoff_sequence: int,
    start_at_ms: int | None,
    end_at_ms: int | None,
    session_id: int | None,
    condition_ids: tuple[str, ...] | None,
    market_slugs: tuple[str, ...] | None,
    token_id: str | None,
    open_only: bool,
) -> tuple[CoverageGapRecord, ...]:
    """Return validated gaps that affect one already-validated selection."""

    clauses: list[str] = [
        f"{ArchiveColumn.EVENT_SEQUENCE} <= ?",
        f"({ArchiveColumn.ENDED_AT_MS} IS NULL OR {ArchiveColumn.ENDED_AT_MS} > {ArchiveColumn.STARTED_AT_MS})",
    ]
    parameters: list[object] = [replay_cutoff_sequence]
    if start_at_ms is not None:
        clauses.append(
            f"({ArchiveColumn.ENDED_AT_MS} IS NULL OR {ArchiveColumn.ENDED_AT_MS} > ?)"
        )
        parameters.append(start_at_ms)
    if end_at_ms is not None:
        clauses.append(f"{ArchiveColumn.STARTED_AT_MS} <= ?")
        parameters.append(end_at_ms)
    if session_id is not None:
        clauses.append(f"{ArchiveColumn.SESSION_ID} = ?")
        parameters.append(session_id)
    if open_only:
        clauses.append(f"{ArchiveColumn.ENDED_AT_MS} IS NULL")
    rows = connection.execute(
        f"SELECT * FROM {COVERAGE_GAPS_TABLE} WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY {ArchiveColumn.STARTED_AT_MS}, {ArchiveColumn.GAP_ID}",
        tuple(parameters),
    ).fetchall()
    result: list[CoverageGapRecord] = []
    for row in rows:
        payload = _typed_payload(
            PayloadKind.COVERAGE_GAP,
            row[ArchiveColumn.PAYLOAD_JSON],
            CoverageGapPayload,
        )
        identity = _identity_from_row(row)
        if not _gap_affects(
            identity,
            payload,
            condition_ids=condition_ids,
            market_slugs=market_slugs,
            token_id=token_id,
        ):
            continue
        if (
            payload.started_at_ms != row[ArchiveColumn.STARTED_AT_MS]
            or payload.ended_at_ms != row[ArchiveColumn.ENDED_AT_MS]
            or payload.reason != row[ArchiveColumn.REASON]
        ):
            raise ArchiveFormatError("coverage gap index is inconsistent")
        try:
            result.append(
                CoverageGapRecord(
                    gap_id=_strict_int(row[ArchiveColumn.GAP_ID], "coverage gap ID"),
                    event_sequence=_strict_int(
                        row[ArchiveColumn.EVENT_SEQUENCE],
                        "coverage gap sequence",
                    ),
                    session_id=_strict_int(
                        row[ArchiveColumn.SESSION_ID],
                        "coverage gap session",
                    ),
                    subscription_generation=_strict_int(
                        row[ArchiveColumn.SUBSCRIPTION_GENERATION],
                        "coverage gap generation",
                    ),
                    observed_at_ms=_strict_int(
                        row[ArchiveColumn.OBSERVED_AT_MS],
                        "coverage gap observation",
                    ),
                    identity=identity,
                    gap=payload,
                )
            )
        except ValueError as error:
            raise ArchiveFormatError("coverage gap record is malformed") from error
    return tuple(result)


def reject_known_gaps(
    connection: sqlite3.Connection,
    *,
    replay_cutoff_sequence: int,
    start_at_ms: int | None,
    end_at_ms: int | None,
    session_id: int | None,
    condition_ids: tuple[str, ...] | None,
    market_slugs: tuple[str, ...] | None,
    token_id: str | None,
) -> None:
    """Reject a selection that overlaps any relevant known coverage gap."""

    gaps = coverage_gaps(
        connection,
        replay_cutoff_sequence=replay_cutoff_sequence,
        start_at_ms=start_at_ms,
        end_at_ms=end_at_ms,
        session_id=session_id,
        condition_ids=condition_ids,
        market_slugs=market_slugs,
        token_id=token_id,
        open_only=False,
    )
    if gaps:
        raise ArchiveCoverageError.for_gap_ids(tuple(gap.gap_id for gap in gaps))
