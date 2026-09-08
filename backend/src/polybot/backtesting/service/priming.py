from __future__ import annotations

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestSelection,
)
from polybot.backtesting.selection.bootstrap import ReplayBootstrap
from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.market import MarketMetadataPayload


def prime_to_start(
    reader: RecordingReader,
    state: ArchiveMarketState,
    selection: BacktestSelection,
    *,
    require_checkpoint_pairs: bool,
) -> int:
    """Materialize metadata and books immediately before the selected range."""
    prime_at_ms = selection.start_at_ms - 1
    markets = (
        ()
        if prime_at_ms < 0
        else reader.markets_at(
            prime_at_ms,
            session_id=selection.session_id,
            market_slugs=selection.market_slugs,
            allow_gaps=True,
        )
    )
    for market in markets:
        materialized = reader.market_state_at(
            market.condition_id,
            prime_at_ms,
            allow_gaps=True,
        )
        state.add_metadata(materialized or market)
    checkpoint_sequences: dict[str, int] = {}
    scan_start_ms = selection.start_at_ms
    for market in markets:
        has_in_range_baselines = reader.has_complete_baseline_pair(
            market,
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.end_at_ms,
            session_id=selection.session_id,
        )
        checkpoints = ReplayBootstrap(reader).checkpoint_pair(
            condition_id=market.condition_id,
            start_at_ms=selection.start_at_ms,
            session_id=selection.session_id,
            allow_pre_gap_checkpoint=(
                selection.gap_policy.allows_gaps
                and ReplayBootstrap(reader).starts_in_market_gap(
                    selection,
                    market,
                )
            ),
        )
        if checkpoints is None:
            if has_in_range_baselines:
                continue
            bounds = reader.event_bounds(
                end_at_ms=selection.start_at_ms,
                session_id=selection.session_id,
                market_slugs=(market.market_slug,),
                allow_gaps=selection.gap_policy.allows_gaps,
            )
            if (
                require_checkpoint_pairs
                and bounds is not None
                and bounds.start_at_ms < selection.start_at_ms
            ):
                raise BacktestError(
                    BacktestFailureReason.MISSING_MARKET_DATA,
                    "mid-session replay requires a common two-token checkpoint "
                    f"for {market.market_slug}",
                )
            scan_start_ms = min(
                scan_start_ms,
                session_start(reader, selection.session_id),
            )
            continue
        if checkpoints[0].observed_at_ms == selection.start_at_ms:
            boundary_metadata = reader.market_state_at(
                market.condition_id,
                selection.start_at_ms,
                sequence_cutoff=checkpoints[0].sequence,
                allow_gaps=True,
            )
            if boundary_metadata is not None:
                state.add_metadata(boundary_metadata)
        state.seed_checkpoints(checkpoints)
        checkpoint_sequences[market.condition_id] = checkpoints[0].sequence
        scan_start_ms = min(scan_start_ms, checkpoints[0].observed_at_ms)
    prime_sequence = max(checkpoint_sequences.values(), default=0)
    events = reader.iter_events(
        start_at_ms=scan_start_ms,
        end_at_ms=selection.start_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
        # Each market's priming interval was validated above. The merged scan
        # can begin before another market's checkpoint, so a set-wide gap check
        # here would reject an otherwise clean subrange.
        allow_gaps=True,
    )
    for event in events:
        if event.observed_at_ms >= selection.start_at_ms:
            continue
        prime_sequence = max(prime_sequence, event.sequence)
        condition_id = None if event.identity is None else event.identity.condition_id
        if event.sequence <= checkpoint_sequences.get(condition_id or "", 0):
            continue
        if isinstance(event.payload, MarketMetadataPayload):
            continue
        if selection.gap_policy.allows_gaps and isinstance(
            event.payload, CoverageGapPayload
        ):
            continue
        state.apply(event)
    return prime_sequence


def session_start(reader: RecordingReader, session_id: int) -> int:
    return reader.select_session(session_id).started_at_ms
