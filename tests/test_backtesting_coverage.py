from __future__ import annotations

from polybot.backtesting.coverage import ReplayCoverage
from polybot.recording.contracts import (
    CoverageGapPayload,
    CoverageGapReason,
    CoverageGapRecord,
    MarketIdentity,
)


def test_replay_coverage_filters_and_unions_clipped_windows() -> None:
    records = (
        _gap_record(1, sequence=11, started_at_ms=50, ended_at_ms=150),
        _gap_record(2, sequence=12, started_at_ms=140, ended_at_ms=200),
        _gap_record(3, sequence=13, started_at_ms=225, ended_at_ms=225),
        _gap_record(4, sequence=14, started_at_ms=250, ended_at_ms=None),
        _gap_record(5, sequence=15, started_at_ms=301, ended_at_ms=350),
    )

    coverage = ReplayCoverage(records, start_at_ms=100, end_at_ms=300)

    assert coverage.gap_ids == (1, 2, 4)
    assert coverage.open_gap_count == 1
    assert coverage.duration_ms == 151
    assert coverage.next_start_at_ms == 100
    assert coverage.next_boundary_at_ms == 100
    assert [record.gap_id for record in coverage.next_start_records] == [1]
    assert [
        record.gap_id for record in coverage.pop_next_start_records()
    ] == [1]
    assert coverage.next_start_at_ms == 140
    assert coverage.next_boundary_at_ms == 140
    assert [
        record.gap_id
        for record in coverage.pop_start_records_through(140)
    ] == [2]
    assert coverage.next_boundary_at_ms == 150
    assert coverage.pop_end_records_through(149) == ()
    assert [
        record.gap_id for record in coverage.pop_end_records_through(200)
    ] == [1, 2]
    assert coverage.next_boundary_at_ms == 250
    assert [
        record.gap_id for record in coverage.pop_start_records_through(250)
    ] == [4]
    assert coverage.next_start_at_ms is None
    assert coverage.next_boundary_at_ms is None


def _gap_record(
    gap_id: int,
    *,
    sequence: int,
    started_at_ms: int,
    ended_at_ms: int | None,
    condition_id: str | None = None,
    market_slug: str | None = None,
    token_ids: tuple[str, ...] = (),
) -> CoverageGapRecord:
    identity = (
        None
        if condition_id is None and market_slug is None
        else MarketIdentity(
            condition_id=condition_id,
            market_slug=market_slug,
        )
    )
    return CoverageGapRecord(
        gap_id=gap_id,
        event_sequence=sequence,
        session_id=1,
        subscription_generation=1,
        observed_at_ms=max(started_at_ms, 0),
        identity=identity,
        gap=CoverageGapPayload(
            reason=CoverageGapReason.DISCONNECT,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            affected_condition_ids=(
                () if condition_id is None else (condition_id,)
            ),
            affected_market_slugs=(
                () if market_slug is None else (market_slug,)
            ),
            affected_token_ids=token_ids,
        ),
    )
