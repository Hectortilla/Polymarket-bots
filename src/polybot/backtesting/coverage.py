"""Coverage-gap selection facts and deterministic start-boundary iteration."""

from __future__ import annotations

from polybot.recording.contracts import CoverageGapRecord, MarketMetadataPayload
from polybot.recording.coverage import CoverageScope


def gaps_affecting_markets(
    records: tuple[CoverageGapRecord, ...],
    markets: tuple[MarketMetadataPayload, ...],
) -> tuple[CoverageGapRecord, ...]:
    """Resolve conservative recorded scopes against concrete selected markets."""

    selected_condition_ids = {market.condition_id for market in markets}
    return tuple(
        record
        for record in records
        if (
            (affected_condition_ids := CoverageScope.from_gap(
                record.gap,
                record.identity,
            ).resolved_condition_ids(markets))
            is None
            or not selected_condition_ids.isdisjoint(affected_condition_ids)
        )
    )


class ReplayCoverage:
    """Own the affecting non-empty gaps for one inclusive replay selection."""

    def __init__(
        self,
        records: tuple[CoverageGapRecord, ...],
        *,
        start_at_ms: int,
        end_at_ms: int,
    ) -> None:
        _validate_timestamp(start_at_ms, "replay coverage start")
        _validate_timestamp(end_at_ms, "replay coverage end")
        if end_at_ms < start_at_ms:
            raise ValueError("replay coverage end cannot precede its start")
        if not isinstance(records, tuple) or not all(
            isinstance(record, CoverageGapRecord) for record in records
        ):
            raise ValueError("replay coverage records must be coverage gaps")

        selected = tuple(
            record
            for record in records
            if _overlaps_selection(
                record,
                start_at_ms=start_at_ms,
                end_at_ms=end_at_ms,
            )
        )
        self._start_at_ms = start_at_ms
        self._end_at_ms = end_at_ms
        self._records = tuple(
            sorted(
                selected,
                key=lambda record: (
                    max(start_at_ms, record.gap.started_at_ms),
                    record.gap_id,
                ),
            )
        )
        self._end_records = tuple(
            sorted(
                (
                    record
                    for record in self._records
                    if record.gap.ended_at_ms is not None
                    and record.gap.ended_at_ms <= end_at_ms
                ),
                key=lambda record: (
                    record.gap.ended_at_ms or 0,
                    record.gap_id,
                ),
            )
        )
        self._next_start_index = 0
        self._next_end_index = 0

    @property
    def records(self) -> tuple[CoverageGapRecord, ...]:
        return self._records

    @property
    def gap_ids(self) -> tuple[int, ...]:
        return tuple(sorted(record.gap_id for record in self._records))

    @property
    def open_gap_count(self) -> int:
        return sum(record.is_open for record in self._records)

    @property
    def duration_ms(self) -> int:
        """Return the unioned wall-clock duration clipped to the selection."""

        intervals = sorted(
            interval
            for record in self._records
            if (
                interval := _clipped_interval(
                    record,
                    start_at_ms=self._start_at_ms,
                    end_at_ms=self._end_at_ms,
                )
            )
            is not None
        )
        if not intervals:
            return 0
        duration_ms = 0
        current_start, current_end = intervals[0]
        for start_at_ms, end_at_ms in intervals[1:]:
            if start_at_ms <= current_end:
                current_end = max(current_end, end_at_ms)
                continue
            duration_ms += current_end - current_start
            current_start, current_end = start_at_ms, end_at_ms
        return duration_ms + current_end - current_start

    @property
    def next_start_at_ms(self) -> int | None:
        if self._next_start_index >= len(self._records):
            return None
        return max(
            self._start_at_ms,
            self._records[self._next_start_index].gap.started_at_ms,
        )

    @property
    def next_end_at_ms(self) -> int | None:
        if self._next_end_index >= len(self._end_records):
            return None
        ended_at_ms = self._end_records[self._next_end_index].gap.ended_at_ms
        if ended_at_ms is None:
            raise AssertionError("open coverage gaps have no end boundary")
        return ended_at_ms

    @property
    def next_boundary_at_ms(self) -> int | None:
        boundaries = tuple(
            boundary
            for boundary in (self.next_start_at_ms, self.next_end_at_ms)
            if boundary is not None
        )
        return None if not boundaries else min(boundaries)

    @property
    def next_start_records(self) -> tuple[CoverageGapRecord, ...]:
        next_start_at_ms = self.next_start_at_ms
        if next_start_at_ms is None:
            return ()
        end = self._next_start_index
        while end < len(self._records) and max(
            self._start_at_ms,
            self._records[end].gap.started_at_ms,
        ) == next_start_at_ms:
            end += 1
        return self._records[self._next_start_index : end]

    def pop_next_start_records(self) -> tuple[CoverageGapRecord, ...]:
        records = self.next_start_records
        self._next_start_index += len(records)
        return records

    def pop_start_records_through(
        self,
        observed_at_ms: int,
    ) -> tuple[CoverageGapRecord, ...]:
        _validate_timestamp(observed_at_ms, "replay coverage boundary")
        records: list[CoverageGapRecord] = []
        while (
            (next_start_at_ms := self.next_start_at_ms) is not None
            and next_start_at_ms <= observed_at_ms
        ):
            records.extend(self.pop_next_start_records())
        return tuple(records)

    def pop_end_records_through(
        self,
        observed_at_ms: int,
    ) -> tuple[CoverageGapRecord, ...]:
        _validate_timestamp(observed_at_ms, "replay coverage boundary")
        start = self._next_end_index
        while (
            (next_end_at_ms := self.next_end_at_ms) is not None
            and next_end_at_ms <= observed_at_ms
        ):
            self._next_end_index += 1
        return self._end_records[start : self._next_end_index]


def _overlaps_selection(
    record: CoverageGapRecord,
    *,
    start_at_ms: int,
    end_at_ms: int,
) -> bool:
    gap = record.gap
    return (
        gap.ended_at_ms != gap.started_at_ms
        and gap.started_at_ms <= end_at_ms
        and (gap.ended_at_ms is None or gap.ended_at_ms > start_at_ms)
    )


def _clipped_interval(
    record: CoverageGapRecord,
    *,
    start_at_ms: int,
    end_at_ms: int,
) -> tuple[int, int] | None:
    gap = record.gap
    clipped_start = max(start_at_ms, gap.started_at_ms)
    selection_end_exclusive = end_at_ms + 1
    clipped_end = min(
        selection_end_exclusive,
        (
            selection_end_exclusive
            if gap.ended_at_ms is None
            else gap.ended_at_ms
        ),
    )
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


def _validate_timestamp(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be nonnegative")
