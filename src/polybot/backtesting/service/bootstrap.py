"""Market-state priming before deterministic replay begins."""

from __future__ import annotations

from polybot.async_io import run_blocking
from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestSelection,
)
from polybot.backtesting.coverage import ReplayCoverage
from polybot.backtesting.scheduler.cursor import ReplayCursor
from polybot.backtesting.selection import (
    replay_start_checkpoint_pair,
    selection_starts_in_market_gap,
)
from polybot.backtesting.state import ArchiveMarketState
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.book import BookBaselinePayload
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.records import RecordedEvent

from .coverage import advance_bootstrap_coverage


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
        checkpoints = replay_start_checkpoint_pair(
            reader,
            condition_id=market.condition_id,
            start_at_ms=selection.start_at_ms,
            session_id=selection.session_id,
            allow_pre_gap_checkpoint=(
                selection.gap_policy.allows_gaps
                and selection_starts_in_market_gap(
                    reader,
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
        if (
            selection.gap_policy.allows_gaps
            and isinstance(event.payload, CoverageGapPayload)
        ):
            continue
        state.apply(event)
    return prime_sequence


async def advance_to_replayable_start(
    reader: RecordingReader,
    bot: BaseBot,
    ctx: BotContext,
    state: ArchiveMarketState,
    clock: ReplayClock,
    selection: BacktestSelection,
    prime_sequence: int,
    *,
    coverage: ReplayCoverage | None,
    explicit_start: bool,
) -> tuple[int, int]:
    """Advance from a default range start until the bot has complete inputs."""
    allow_blackouts = selection.gap_policy.allows_gaps
    if await _plan_is_replayable(
        bot,
        ctx,
        state,
        allow_blackouts=allow_blackouts,
    ):
        return selection.start_at_ms, prime_sequence
    events = await run_blocking(
        reader.iter_events,
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
        allow_gaps=allow_blackouts,
    )
    cursor = ReplayCursor(events, after_sequence=prime_sequence)
    try:
        while (event := await cursor.pop()) is not None:
            if explicit_start and event.observed_at_ms > selection.start_at_ms:
                break
            advance_bootstrap_coverage(
                state,
                clock,
                coverage,
                through_ms=event.observed_at_ms,
            )
            clock.move_to(event.observed_at_ms)
            if not isinstance(event.payload, CoverageGapPayload):
                state.apply(event)
            prime_sequence = event.sequence
            if not await _plan_is_replayable(
                bot,
                ctx,
                state,
                allow_blackouts=allow_blackouts,
            ):
                continue
            while (
                (same_boundary := await cursor.peek()) is not None
                and same_boundary.observed_at_ms == event.observed_at_ms
                and _is_priming_state_event(same_boundary)
            ):
                current = await cursor.pop()
                if current is None:
                    break
                state.apply(current)
                prime_sequence = current.sequence
            if await _plan_is_replayable(
                bot,
                ctx,
                state,
                allow_blackouts=allow_blackouts,
            ):
                return event.observed_at_ms, prime_sequence
    finally:
        await cursor.aclose()
    if explicit_start:
        raise BacktestError(
            BacktestFailureReason.MISSING_MARKET_DATA,
            "selected start has no complete books for the bot's current markets",
        )
    raise BacktestError(
        BacktestFailureReason.MISSING_MARKET_DATA,
        "recording never provides complete books for the bot's current markets",
    )


def _is_priming_state_event(event: RecordedEvent) -> bool:
    return isinstance(event.payload, BookBaselinePayload) or (
        isinstance(event.payload, MarketMetadataPayload)
        and not event.payload.resolved
    )


async def _plan_is_replayable(
    bot: BaseBot,
    ctx: BotContext,
    state: ArchiveMarketState,
    *,
    allow_blackouts: bool,
) -> bool:
    now_ms = ctx.clock.now_ms()
    current = await bot.current_stream_rules(ctx, now_ms)
    next_rules = await bot.next_stream_rules(ctx, now_ms)
    if any(rule.wallet_addresses for rule in (*current, *next_rules)):
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            "wallet stream rules cannot be replayed from a market-only archive",
        )
    current_slugs = {slug for rule in current for slug in rule.market_slugs}
    if current_slugs:
        return all(
            _market_is_replayable(
                state,
                slug,
                allow_blackouts=allow_blackouts,
            )
            for slug in current_slugs
        )
    return any(
        _market_is_replayable(
            state,
            slug,
            allow_blackouts=allow_blackouts,
        )
        for slug in state.market_slugs
    )


def _market_is_replayable(
    state: ArchiveMarketState,
    market_slug: str,
    *,
    allow_blackouts: bool,
) -> bool:
    return state.has_complete_book(market_slug) or (
        allow_blackouts
        and state.is_blacked_out(market_slug)
        and state.has_bootstrap_evidence(market_slug)
    )


def session_start(reader: RecordingReader, session_id: int) -> int:
    return reader.select_session(session_id).started_at_ms
