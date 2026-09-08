from __future__ import annotations

from polybot.recording.archive.models import RecordingSession
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.trim_recovery.boundaries import RecoveryTokenBoundary


class TrimRecovery:
    def __init__(self, reader: RecordingReader) -> None:
        self._reader = reader

    def token_boundaries(
        self,
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
                for record in self._reader.coverage_gaps(
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

    def clean_scan_start(
        self,
        *,
        session: RecordingSession,
        condition_id: str,
        through_ms: int,
    ) -> int | None:
        """Return the safe replay start after relevant gaps, or ``None`` if absent."""
        scan_start_ms = session.started_at_ms
        if through_ms < scan_start_ms:
            return None
        for record in self._reader.coverage_gaps(
            start_at_ms=scan_start_ms,
            end_at_ms=through_ms,
            session_id=session.session_id,
            condition_id=condition_id,
        ):
            if record.gap.ended_at_ms is None:
                return None
            scan_start_ms = max(scan_start_ms, record.gap.ended_at_ms)
        return scan_start_ms if scan_start_ms <= through_ms else None
