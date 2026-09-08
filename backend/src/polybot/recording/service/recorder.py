"""Public-data recorder assembly and lifecycle."""

from __future__ import annotations

import asyncio
from pathlib import Path

from polybot.async_io import run_blocking
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.polymarket.public_data.recording import RecordingPublicData
from polybot.recording.clock import ObservationClock
from polybot.recording.coordinator import RecordingCoordinator
from polybot.recording.planning import (
    BotStreamPlanProvider,
    StaticStreamPlanProvider,
    planning_context,
)
from polybot.recording.writer import AsyncRecordingWriter

from .lifecycle import (
    close_recording_sources,
    finish_recording,
    run_until_stopped,
)
from .markets import resolve_initial_markets
from .resume import ResumeState, read_resume_state
from .session import start_recording_session


NO_CURRENT_MARKETS_MESSAGE = (
    "the recorder requires at least one current market subscription"
)
CANCELLED_RECORDING_REASON = "recording task was cancelled before clean shutdown"


async def record_markets(
    config: BotConfig,
    *,
    output_path: Path,
    target_identity: str,
    bot: BaseBot | None = None,
    market_slugs: tuple[str, ...] = (),
    duration_seconds: int | None = None,
    resume: bool = False,
    public_data: RecordingPublicData | None = None,
) -> None:
    """Record static or bot-planned markets into one replay-ready archive."""
    if (bot is None) == (not market_slugs):
        raise ValueError("provide either a bot or static market slugs")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("recording duration must be positive")

    clock = ObservationClock()
    resume_state = (
        await run_blocking(read_resume_state, output_path, target_identity)
        if resume
        else ResumeState((), None)
    )
    if resume_state.clock_floor_ms is not None:
        clock.advance_to(resume_state.clock_floor_ms)

    sources = (
        RecordingPublicData.create()
        if public_data is None
        else public_data
    )
    writer: AsyncRecordingWriter | None = None
    coordinator: RecordingCoordinator | None = None
    try:
        resolver = sources.resolver
        feed = sources.feed
        gamma = sources.gamma
        clob = sources.clob
        provider = (
            BotStreamPlanProvider(
                bot,
                planning_context(config, markets=gamma, books=clob),
            )
            if bot is not None
            else StaticStreamPlanProvider(market_slugs)
        )
        initial_plan = await provider.plan(clock.now_ms())
        if not initial_plan.current_market_slugs:
            raise RuntimeError(NO_CURRENT_MARKETS_MESSAGE)
        initial_markets, missing_restored = await resolve_initial_markets(
            resolver,
            initial_plan,
            resume_state.restored_slugs,
        )

        started_session = await start_recording_session(
            output_path=output_path,
            target_identity=target_identity,
            resume=resume,
            clock=clock,
        )
        writer = started_session.writer

        coordinator = RecordingCoordinator(
            provider=provider,
            resolver=resolver,
            feed=feed,
            writer=writer,
            clock=clock,
            stop_when_terminal=bot is None,
            resumed_gap_conditions_by_id=dict(
                resume_state.open_gap_conditions_by_id
            ),
        )
        await coordinator.start(
            initial_plan,
            initial_markets,
            retained_missing_slugs=missing_restored,
        )
        await run_until_stopped(
            coordinator,
            duration_seconds=duration_seconds,
        )
    except asyncio.CancelledError:
        await finish_recording(
            coordinator,
            writer,
            clean=False,
            failure_reason=CANCELLED_RECORDING_REASON,
            suppress_errors=True,
        )
        raise
    except BaseException as error:
        await finish_recording(
            coordinator,
            writer,
            clean=False,
            failure_reason=f"{type(error).__name__}: {error}",
            suppress_errors=True,
        )
        raise
    else:
        await finish_recording(coordinator, writer, clean=True)
    finally:
        await close_recording_sources(sources)
