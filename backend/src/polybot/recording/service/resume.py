"""Resume-state recovery for an existing recording archive."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.records import CoverageGapRecord
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.coverage import CoverageScope


@dataclass(frozen=True, slots=True)
class ResumeState:
    restored_slugs: tuple[str, ...]
    clock_floor_ms: int | None
    open_gap_conditions_by_id: tuple[tuple[int, frozenset[str]], ...] = ()


def read_resume_state(path: Path, target_identity: str) -> ResumeState:
    """Read the minimum state needed to continue a compatible archive."""
    with RecordingReader(path) as reader:
        if reader.target_identity != target_identity:
            raise ValueError("recording archive target identity does not match")
        sessions = reader.sessions()
        session_boundary = (
            None
            if not sessions
            else sessions[-1].ended_at_ms or sessions[-1].started_at_ms
        )
        observed_boundary = reader.last_observed_at_ms
        boundaries = tuple(
            boundary
            for boundary in (session_boundary, observed_boundary)
            if boundary is not None
        )
        open_gaps = reader.coverage_gaps(open_only=True)
        restored_by_condition = {
            metadata.condition_id: metadata
            for metadata in reader.unresolved_markets()
        }
        lookup_at_ms = max(boundaries) if boundaries else 0
        for condition_id in explicit_gap_condition_ids(open_gaps):
            if condition_id in restored_by_condition:
                continue
            metadata = reader.market_at(
                condition_id,
                lookup_at_ms,
                allow_gaps=True,
            )
            if metadata is not None:
                restored_by_condition[condition_id] = metadata
        restored = tuple(
            restored_by_condition[condition_id]
            for condition_id in sorted(restored_by_condition)
        )
        return ResumeState(
            restored_slugs=tuple(metadata.market_slug for metadata in restored),
            clock_floor_ms=max(boundaries) if boundaries else None,
            open_gap_conditions_by_id=open_gap_conditions_by_id(open_gaps, restored),
        )


def explicit_gap_condition_ids(
    gaps: tuple[CoverageGapRecord, ...],
) -> frozenset[str]:
    """Return condition IDs explicitly named by open coverage gaps."""
    conditions: set[str] = set()
    for record in gaps:
        conditions.update(
            CoverageScope.from_gap(record.gap, record.identity).condition_ids
        )
    return frozenset(conditions)


def open_gap_conditions_by_id(
    gaps: tuple[CoverageGapRecord, ...],
    unresolved: tuple[MarketMetadataPayload, ...],
) -> tuple[tuple[int, frozenset[str]], ...]:
    """Resolve the market scope each still-open gap should retain on resume."""
    all_conditions = frozenset(market.condition_id for market in unresolved)
    result: list[tuple[int, frozenset[str]]] = []
    for record in gaps:
        resolved = CoverageScope.from_gap(
            record.gap,
            record.identity,
        ).resolved_condition_ids(unresolved)
        conditions = all_conditions if resolved is None else resolved
        if conditions:
            result.append((record.gap_id, frozenset(conditions)))
    return tuple(result)
