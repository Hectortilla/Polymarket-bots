"""Scheduler execution and artifact finalization for a prepared replay."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from polybot.async_io import run_blocking
from polybot.backtesting.broker import BacktestPerformanceBroker
from polybot.backtesting.clients import (
    RejectingPositionClient,
    RejectingWalletActivityClient,
)
from polybot.backtesting.scheduler.cursor import ReplayCursor
from polybot.backtesting.scheduler.replay import ReplayScheduler
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.runner import BotRunner
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.contracts.run import PerformanceRunStatus
from polybot.recording.archive.reader import RecordingReader

from .setup import PreparedReplay


@dataclass(frozen=True, slots=True)
class ReplayExecutionResult:
    event_count: int
    accepted_dispatch_count: int
    skipped_dispatch_count: int
    resolution_count: int


async def execute_replay(
    reader: RecordingReader,
    bot: BaseBot,
    config: BotConfig,
    *,
    prepared: PreparedReplay,
    artifacts: PerformanceArtifacts,
) -> ReplayExecutionResult:
    paper_broker = prepared.paper_broker
    clock = prepared.clock
    broker = BacktestPerformanceBroker(
        paper_broker,
        clock=clock,
        artifacts=artifacts,
        portfolio=paper_broker.portfolio,
    )
    context = BotContext(
        config=config,
        broker=broker,
        markets=prepared.state,
        books=prepared.state,
        wallet_activity=RejectingWalletActivityClient(),
        positions=RejectingPositionClient(),
        clock=clock,
        rng=prepared.strategy_rng,
    )
    runner = BotRunner(bot, context, now_ms_fn=clock.now_ms)
    selection = prepared.selection
    events = await run_blocking(
        reader.iter_events,
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
        session_id=selection.session_id,
        market_slugs=selection.market_slugs,
        allow_gaps=selection.gap_policy.allows_gaps,
    )
    scheduler = ReplayScheduler(
        bot=bot,
        runner=runner,
        paper_broker=paper_broker,
        state=prepared.state,
        clock=clock,
        cursor=ReplayCursor(events, after_sequence=prepared.prime_sequence),
        artifacts=artifacts,
        coverage=prepared.coverage,
    )
    try:
        await scheduler.run()
    except asyncio.CancelledError:
        await _finalize(
            artifacts,
            status=PerformanceRunStatus.CANCELLED,
            prepared=prepared,
        )
        raise
    except BaseException as error:
        await _finalize(
            artifacts,
            status=PerformanceRunStatus.FAILED,
            prepared=prepared,
            error=f"{type(error).__name__}: {error}",
        )
        raise
    await _finalize(
        artifacts,
        status=PerformanceRunStatus.COMPLETED,
        prepared=prepared,
    )
    return ReplayExecutionResult(
        event_count=scheduler.event_count,
        accepted_dispatch_count=scheduler.accepted_dispatch_count,
        skipped_dispatch_count=scheduler.skipped_dispatch_count,
        resolution_count=scheduler.resolution_count,
    )


async def _finalize(
    artifacts: PerformanceArtifacts,
    *,
    status: PerformanceRunStatus,
    prepared: PreparedReplay,
    error: str | None = None,
) -> None:
    await run_blocking(
        artifacts.finalize,
        status=status,
        ended_at_ms=prepared.clock.now_ms(),
        portfolio=prepared.paper_broker.portfolio,
        error=error,
    )
