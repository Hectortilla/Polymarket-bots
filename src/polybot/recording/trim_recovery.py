"""Sequence-aware recovery boundaries for recording trims."""

from __future__ import annotations

from dataclasses import dataclass

from .archive import RecordingReader
from .archive_models import RecordingSession
from .contracts import MarketMetadataPayload


@dataclass(frozen=True, slots=True)
class RecoveryTokenBoundary:
    token_id: str
    start_at_ms: int
    after_sequence: int


def recovery_token_boundaries(
    source: RecordingReader,
    *,
    session: RecordingSession,
    market: MarketMetadataPayload,
    boundary_at_ms: int,
) -> tuple[RecoveryTokenBoundary, ...] | None:
    """Return each token's latest applicable gap boundary, when any exists."""

    boundaries: list[RecoveryTokenBoundary] = []
    has_gap = False
    for outcome in market.outcomes:
        closed_gaps = tuple(
            record
            for record in source.coverage_gaps(
                start_at_ms=session.started_at_ms,
                end_at_ms=boundary_at_ms,
                session_id=session.session_id,
                condition_id=market.condition_id,
                token_id=outcome.token_id,
            )
            if record.gap.ended_at_ms is not None
            and record.gap.ended_at_ms <= boundary_at_ms
        )
        if not closed_gaps:
            boundaries.append(
                RecoveryTokenBoundary(
                    token_id=outcome.token_id,
                    start_at_ms=session.started_at_ms,
                    after_sequence=0,
                )
            )
            continue
        has_gap = True
        latest = max(closed_gaps, key=lambda record: record.event_sequence)
        boundaries.append(
            RecoveryTokenBoundary(
                token_id=outcome.token_id,
                start_at_ms=latest.gap.started_at_ms,
                after_sequence=latest.event_sequence,
            )
        )
    if not has_gap:
        return None
    return tuple(boundaries)


def recovery_sequence_cutoffs(
    boundaries: tuple[RecoveryTokenBoundary, ...] | None,
) -> dict[str, int] | None:
    """Convert recovery boundaries into strict per-token sequence floors."""

    if boundaries is None:
        return None
    return {
        boundary.token_id: boundary.after_sequence for boundary in boundaries
    }
