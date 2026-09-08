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
from polybot.backtesting.service.coverage import advance_bootstrap_coverage
from polybot.backtesting.state import ArchiveMarketState
from polybot.backtesting.validation import replay_rule_issue
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.contracts.book import BookBaselinePayload
from polybot.recording.contracts.gaps import CoverageGapPayload
from polybot.recording.contracts.market import MarketMetadataPayload
from polybot.recording.contracts.records import RecordedEvent


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
                priming_event = await cursor.pop()
                if priming_event is None:
                    break
                state.apply(priming_event)
                prime_sequence = priming_event.sequence
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
        isinstance(event.payload, MarketMetadataPayload) and not event.payload.resolved
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
    if issue := replay_rule_issue((*current, *next_rules)):
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            issue,
        )
    current_slugs = {slug for rule in current for slug in rule.market_slugs}
    if current_slugs:
        return all(
            state.market_is_replayable(
                slug,
                allow_blackouts=allow_blackouts,
            )
            for slug in current_slugs
        )
    return any(
        state.market_is_replayable(
            slug,
            allow_blackouts=allow_blackouts,
        )
        for slug in state.market_slugs
    )
