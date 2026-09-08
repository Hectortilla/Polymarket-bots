"""Coverage-gap queries and replay-safety validation for archive reads."""

from __future__ import annotations

import sqlite3

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
        "event_sequence <= ?",
        "(ended_at_ms IS NULL OR ended_at_ms > started_at_ms)",
    ]
    parameters: list[object] = [replay_cutoff_sequence]
    if start_at_ms is not None:
        clauses.append("(ended_at_ms IS NULL OR ended_at_ms > ?)")
        parameters.append(start_at_ms)
    if end_at_ms is not None:
        clauses.append("started_at_ms <= ?")
        parameters.append(end_at_ms)
    if session_id is not None:
        clauses.append("session_id = ?")
        parameters.append(session_id)
    if open_only:
        clauses.append("ended_at_ms IS NULL")
    rows = connection.execute(
        "SELECT * FROM coverage_gaps WHERE "
        + " AND ".join(clauses)
        + " ORDER BY started_at_ms, gap_id",
        tuple(parameters),
    ).fetchall()
    result: list[CoverageGapRecord] = []
    for row in rows:
        payload = _typed_payload(
            PayloadKind.COVERAGE_GAP,
            row["payload_json"],
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
            payload.started_at_ms != row["started_at_ms"]
            or payload.ended_at_ms != row["ended_at_ms"]
            or payload.reason != row["reason"]
        ):
            raise ArchiveFormatError("coverage gap index is inconsistent")
        try:
            result.append(
                CoverageGapRecord(
                    gap_id=_strict_int(row["gap_id"], "coverage gap ID"),
                    event_sequence=_strict_int(
                        row["event_sequence"],
                        "coverage gap sequence",
                    ),
                    session_id=_strict_int(
                        row["session_id"],
                        "coverage gap session",
                    ),
                    subscription_generation=_strict_int(
                        row["subscription_generation"],
                        "coverage gap generation",
                    ),
                    observed_at_ms=_strict_int(
                        row["observed_at_ms"],
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
