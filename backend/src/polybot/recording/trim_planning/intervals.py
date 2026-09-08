from __future__ import annotations

from dataclasses import dataclass

from polybot.recording.contracts.records import CoverageGapRecord


@dataclass(frozen=True, slots=True)
class CleanInterval:
    start_at_ms: int
    end_at_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_at_ms - self.start_at_ms


def candidate_sort_key(value: CleanInterval) -> tuple[int, int, int]:
    return (-value.duration_ms, value.start_at_ms, value.end_at_ms)


def clean_intervals(
    session_start_ms: int,
    session_end_ms: int,
    gaps: tuple[CoverageGapRecord, ...],
) -> tuple[CleanInterval, ...]:
    cursor = session_start_ms
    intervals: list[CleanInterval] = []
    for record in sorted(gaps, key=lambda value: value.gap.started_at_ms):
        gap = record.gap
        if gap.is_instantaneous:
            continue
        if gap.started_at_ms > session_end_ms:
            break
        if gap.ended_at_ms is not None and gap.ended_at_ms <= cursor:
            continue
        gap_start = max(session_start_ms, gap.started_at_ms)
        if gap_start > cursor:
            intervals.append(CleanInterval(cursor, gap_start - 1))
        gap_end = (
            session_end_ms + 1
            if gap.ended_at_ms is None
            else min(session_end_ms + 1, gap.ended_at_ms)
        )
        cursor = max(cursor, gap_end)
        if cursor > session_end_ms:
            break
    if cursor <= session_end_ms:
        intervals.append(CleanInterval(cursor, session_end_ms))
    return tuple(intervals)
