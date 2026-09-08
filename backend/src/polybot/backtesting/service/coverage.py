"""Coverage-gap preparation while bootstrapping a deterministic replay."""

from __future__ import annotations

from polybot.async_io import run_blocking
from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import BacktestSelection
from polybot.backtesting.coverage import ReplayCoverage
from polybot.backtesting.coverage_selection import gaps_affecting_markets
from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.records import CoverageGapRecord


async def load_replay_coverage(
    reader: RecordingReader,
    selection: BacktestSelection,
) -> ReplayCoverage | None:
    """Load selected gaps only when blackout replay explicitly allows them."""
    if not selection.gap_policy.allows_gaps:
        return None
    records = await run_blocking(selected_coverage_gaps, reader, selection)
    return ReplayCoverage(
        records,
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
    )


def selected_coverage_gaps(
    reader: RecordingReader,
    selection: BacktestSelection,
) -> tuple[CoverageGapRecord, ...]:
    """Return gaps that affect the markets selected for this replay."""
    markets = reader.markets_at(
        selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
        allow_gaps=True,
    )
    records = reader.coverage_gaps(
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
        session_id=selection.session_id,
    )
    return gaps_affecting_markets(records, markets)


def activate_bootstrap_blackouts(
    state: ArchiveMarketState,
    coverage: ReplayCoverage | None,
    *,
    through_ms: int,
) -> None:
    """Apply gap starts that predate a replay boundary."""
    if coverage is None:
        return
    for record in coverage.pop_start_records_through(through_ms):
        state.begin_blackout(record)


def advance_bootstrap_coverage(
    state: ArchiveMarketState,
    clock: ReplayClock,
    coverage: ReplayCoverage | None,
    *,
    through_ms: int,
) -> None:
    """Move the clock through known gap boundaries before applying an event."""
    if coverage is None:
        return
    while (
        (boundary_ms := coverage.next_boundary_at_ms) is not None
        and boundary_ms <= through_ms
    ):
        clock.move_to(boundary_ms)
        activate_bootstrap_blackouts(
            state,
            coverage,
            through_ms=boundary_ms,
        )
        if coverage.pop_end_records_through(boundary_ms):
            state.recover_books_at(boundary_ms)
