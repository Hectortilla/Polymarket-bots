"""Standalone public-data recorder assembly and lifecycle."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from polymarket import AsyncPublicClient

from polybot.async_io import run_blocking
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.streams import StreamPlan
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.recording_feed import MarketRecordingFeed
from polybot.polymarket.recording_metadata import (
    RecordingMarket,
    RecordingMarketResolver,
)
from polybot.recording.archive import RecordingArchive, RecordingReader
from polybot.recording.clock import ObservationClock
from polybot.recording.contracts import (
    CoverageGapPayload,
    CoverageGapRecord,
    MarketMetadataPayload,
)
from polybot.recording.coordinator import RecordingCoordinator
from polybot.recording.planning import (
    BotStreamPlanProvider,
    StaticStreamPlanProvider,
    planning_context,
)
from polybot.recording.writer import AsyncRecordingWriter


NO_CURRENT_MARKETS_MESSAGE = (
    "the recorder requires at least one current market subscription"
)
CANCELLED_RECORDING_REASON = "recording task was cancelled before clean shutdown"


@dataclass(frozen=True, slots=True)
class _ResumeState:
    restored_slugs: tuple[str, ...]
    clock_floor_ms: int | None
    open_gap_condition_ids: tuple[tuple[int, frozenset[str]], ...] = ()


async def record_markets(
    config: BotConfig,
    *,
    output_path: Path,
    target_identity: str,
    bot: BaseBot | None = None,
    market_slugs: tuple[str, ...] = (),
    duration_seconds: int | None = None,
    resume: bool = False,
    client: AsyncPublicClient | None = None,
) -> None:
    """Record static or bot-planned markets into one replay-ready archive."""
    if (bot is None) == (not market_slugs):
        raise ValueError("provide either a bot or static market slugs")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("recording duration must be positive")

    clock = ObservationClock()
    resume_state = (
        await run_blocking(_read_resume_state, output_path, target_identity)
        if resume
        else _ResumeState((), None)
    )
    if resume_state.clock_floor_ms is not None:
        clock.advance_to(resume_state.clock_floor_ms)

    public_client = client or AsyncPublicClient()
    owns_client = client is None
    resolver = RecordingMarketResolver(public_client)
    feed = MarketRecordingFeed(public_client)
    gamma = GammaClient(public_client)
    clob = ClobClient(public_client)
    provider = (
        BotStreamPlanProvider(
            bot,
            planning_context(config, markets=gamma, books=clob),
        )
        if bot is not None
        else StaticStreamPlanProvider(market_slugs)
    )
    writer: AsyncRecordingWriter | None = None
    coordinator: RecordingCoordinator | None = None
    try:
        initial_plan = await provider.plan(clock.now_ms())
        if not initial_plan.current_market_slugs:
            raise RuntimeError(NO_CURRENT_MARKETS_MESSAGE)
        initial_markets, missing_restored = await _resolve_initial_markets(
            resolver,
            initial_plan,
            resume_state.restored_slugs,
        )

        session_started_at_ms = clock.now_ms()
        archive = await run_blocking(
            RecordingArchive.resume if resume else RecordingArchive.create,
            output_path,
            target_identity=target_identity,
            started_at_ms=session_started_at_ms,
        )
        writer = AsyncRecordingWriter(archive)
        writer.start()
        if resume:
            gap_started_at_ms = archive.resume_from_ms
            if gap_started_at_ms is None:
                raise AssertionError("resumed archive has no prior boundary")
            clock.advance_to(gap_started_at_ms)
            session_started_at_ms = clock.now_ms()
            await writer.open_gap(
                CoverageGapPayload(
                    reason="recorder_offline",
                    started_at_ms=gap_started_at_ms,
                    ended_at_ms=session_started_at_ms,
                ),
                observed_at_ms=session_started_at_ms,
                identity=None,
                subscription_generation=0,
            )

        coordinator = RecordingCoordinator(
            provider=provider,
            resolver=resolver,
            feed=feed,
            writer=writer,
            clock=clock,
            stop_when_terminal=bot is None,
            resumed_gap_condition_ids=dict(
                resume_state.open_gap_condition_ids
            ),
        )
        await coordinator.start(
            initial_plan,
            initial_markets,
            retained_missing_slugs=missing_restored,
        )
        await _run_until_stopped(
            coordinator,
            duration_seconds=duration_seconds,
        )
    except asyncio.CancelledError:
        await _finish_recording(
            coordinator,
            writer,
            clean=False,
            failure_reason=CANCELLED_RECORDING_REASON,
            suppress_errors=True,
        )
        raise
    except BaseException as error:
        await _finish_recording(
            coordinator,
            writer,
            clean=False,
            failure_reason=f"{type(error).__name__}: {error}",
            suppress_errors=True,
        )
        raise
    else:
        await _finish_recording(coordinator, writer, clean=True)
    finally:
        await _close_recording_sources(
            feed,
            resolver,
            public_client if owns_client else None,
        )


async def _resolve_initial_markets(
    resolver: RecordingMarketResolver,
    plan: StreamPlan,
    restored_slugs: Iterable[str],
) -> tuple[tuple[RecordingMarket, ...], tuple[str, ...]]:
    restored = tuple(dict.fromkeys(restored_slugs))
    requested = tuple(
        dict.fromkeys(
            (
                *plan.current_market_slugs,
                *plan.next_market_slugs,
                *restored,
            )
        )
    )
    resolved = await resolver.find_many(requested)
    by_slug = dict(zip(requested, resolved, strict=True))
    missing_current = tuple(
        slug for slug in plan.current_market_slugs if by_slug[slug] is None
    )
    if missing_current:
        raise RuntimeError(
            "initial current markets could not be resolved: "
            + ", ".join(missing_current)
        )
    markets = tuple(recording for recording in resolved if recording is not None)
    missing_restored = tuple(slug for slug in restored if by_slug[slug] is None)
    return markets, missing_restored


def _read_resume_state(path: Path, target_identity: str) -> _ResumeState:
    with RecordingReader(path) as reader:
        if reader.target_identity != target_identity:
            raise ValueError("recording archive target identity does not match")
        sessions = reader.sessions()
        session_boundary = (
            None
            if not sessions
            else sessions[-1].ended_at_ms or sessions[-1].started_at_ms
        )
        observed_boundary = reader.last_observed_at_ms
        boundaries = tuple(
            boundary
            for boundary in (session_boundary, observed_boundary)
            if boundary is not None
        )
        open_gaps = reader.coverage_gaps(open_only=True)
        restored_by_condition = {
            metadata.condition_id: metadata
            for metadata in reader.unresolved_markets()
        }
        lookup_at_ms = max(boundaries) if boundaries else 0
        for condition_id in _explicit_gap_condition_ids(open_gaps):
            if condition_id in restored_by_condition:
                continue
            metadata = reader.market_at(
                condition_id,
                lookup_at_ms,
                allow_gaps=True,
            )
            if metadata is not None:
                restored_by_condition[condition_id] = metadata
        restored = tuple(
            restored_by_condition[condition_id]
            for condition_id in sorted(restored_by_condition)
        )
        return _ResumeState(
            restored_slugs=tuple(metadata.market_slug for metadata in restored),
            clock_floor_ms=max(boundaries) if boundaries else None,
            open_gap_condition_ids=_open_gap_condition_ids(
                open_gaps,
                restored,
            ),
        )


def _explicit_gap_condition_ids(
    gaps: tuple[CoverageGapRecord, ...],
) -> frozenset[str]:
    conditions: set[str] = set()
    for record in gaps:
        conditions.update(record.gap.affected_condition_ids)
        if record.identity is not None and record.identity.condition_id is not None:
            conditions.add(record.identity.condition_id)
    return frozenset(conditions)


def _open_gap_condition_ids(
    gaps: tuple[CoverageGapRecord, ...],
    unresolved: tuple[MarketMetadataPayload, ...],
) -> tuple[tuple[int, frozenset[str]], ...]:
    by_slug = {market.market_slug: market.condition_id for market in unresolved}
    by_token = {
        outcome.token_id: market.condition_id
        for market in unresolved
        for outcome in market.outcomes
    }
    all_conditions = frozenset(market.condition_id for market in unresolved)
    result: list[tuple[int, frozenset[str]]] = []
    for record in gaps:
        gap = record.gap
        has_payload_scope = bool(
            gap.affected_condition_ids
            or gap.affected_market_slugs
            or gap.affected_token_ids
        )
        conditions = set(gap.affected_condition_ids)
        conditions.update(
            condition_id
            for slug in gap.affected_market_slugs
            if (condition_id := by_slug.get(slug)) is not None
        )
        conditions.update(
            condition_id
            for token_id in gap.affected_token_ids
            if (condition_id := by_token.get(token_id)) is not None
        )
        identity = record.identity
        if not has_payload_scope and identity is not None:
            if identity.condition_id is not None:
                conditions.add(identity.condition_id)
            if (
                identity.market_slug is not None
                and (condition_id := by_slug.get(identity.market_slug)) is not None
            ):
                conditions.add(condition_id)
            if (
                identity.token_id is not None
                and (condition_id := by_token.get(identity.token_id)) is not None
            ):
                conditions.add(condition_id)
        if not has_payload_scope and identity is None:
            conditions.update(all_conditions)
        if conditions:
            result.append((record.gap_id, frozenset(conditions)))
    return tuple(result)


async def _run_until_stopped(
    coordinator: RecordingCoordinator,
    *,
    duration_seconds: int | None,
) -> None:
    shutdown = asyncio.Event()
    remove_signal_handlers = _install_signal_handlers(shutdown)
    duration_task = (
        None
        if duration_seconds is None
        else asyncio.create_task(_set_after(duration_seconds, shutdown))
    )
    try:
        await coordinator.run(shutdown)
    finally:
        remove_signal_handlers()
        if duration_task is not None:
            duration_task.cancel()
            await asyncio.gather(duration_task, return_exceptions=True)


def _install_signal_handlers(shutdown: asyncio.Event) -> Callable[[], None]:
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, shutdown.set)
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(signum)

    def remove() -> None:
        for signum in installed:
            loop.remove_signal_handler(signum)

    return remove


async def _set_after(seconds: int, event: asyncio.Event) -> None:
    await asyncio.sleep(seconds)
    event.set()


async def _finish_recording(
    coordinator: RecordingCoordinator | None,
    writer: AsyncRecordingWriter | None,
    *,
    clean: bool,
    failure_reason: str | None = None,
    suppress_errors: bool = False,
) -> None:
    cleanup_error: BaseException | None = None
    if coordinator is not None:
        try:
            await coordinator.close()
        except BaseException as error:
            cleanup_error = error
    if writer is not None:
        writer_clean = clean and cleanup_error is None
        writer_reason = failure_reason
        if not writer_clean and writer_reason is None:
            writer_reason = (
                "recording coordinator cleanup failed"
                if cleanup_error is None
                else f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
        try:
            await writer.stop(
                clean=writer_clean,
                failure_reason=writer_reason,
            )
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
    if cleanup_error is not None and not suppress_errors:
        raise cleanup_error


async def _close_recording_sources(
    feed: MarketRecordingFeed,
    resolver: RecordingMarketResolver,
    client: AsyncPublicClient | None,
) -> None:
    for close in (
        feed.close,
        resolver.close,
        None if client is None else client.close,
    ):
        if close is None:
            continue
        try:
            await close()
        except BaseException:
            pass
