"""Construction and lifecycle of one deterministic archive replay."""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from dataclasses import replace
from pathlib import Path

from polybot.async_io import run_blocking
from polybot.backtesting.broker import BacktestPerformanceBroker
from polybot.backtesting.clients import (
    RejectingPositionClient,
    RejectingPlanningBroker,
    RejectingWalletActivityClient,
)
from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestGapPolicy,
    BacktestOptions,
    BacktestResult,
    BacktestSelection,
)
from polybot.backtesting.coverage import ReplayCoverage, gaps_affecting_markets
from polybot.backtesting.scheduler import ReplayCursor, ReplayScheduler
from polybot.backtesting.selection import (
    replay_start_checkpoint_pair,
    resolve_backtest_selection,
    selection_starts_in_market_gap,
    validate_backtest_selection,
)
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig, BotMode
from polybot.framework.context import BotContext
from polybot.framework.runner import BotRunner
from polybot.performance.artifacts import PerformanceArtifacts
from polybot.performance.contracts import (
    PerformanceRunKind,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
)
from polybot.recording.archive import RecordingReader
from polybot.recording.archive_errors import (
    ArchiveCoverageError,
    ArchiveFormatError,
    ArchiveIntegrityError,
    ArchiveLockedError,
    RecordingArchiveError,
)
from polybot.recording.contracts import (
    BookBaselinePayload,
    CoverageGapPayload,
    CoverageGapRecord,
    MarketMetadataPayload,
    RecordedEvent,
)


async def run_backtest(
    bot: BaseBot,
    config: BotConfig,
    *,
    bot_spec: str,
    options: BacktestOptions,
) -> BacktestResult:
    if config.mode is BotMode.LIVE:
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            "backtesting cannot run with BOT_MODE=live",
        )
    try:
        reader = await run_blocking(RecordingReader.for_replay, options.archive_path)
    except ArchiveLockedError as error:
        raise BacktestError(
            BacktestFailureReason.SESSION_NOT_REPLAYABLE,
            str(error),
        ) from error
    except ArchiveFormatError as error:
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_ARCHIVE,
            str(error),
        ) from error
    except RecordingArchiveError as error:
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_ARCHIVE,
            str(error),
        ) from error

    try:
        try:
            session = await run_blocking(reader.select_session, options.session_id)
            selection = await run_blocking(
                resolve_backtest_selection,
                reader,
                session,
                options,
            )
            await run_blocking(validate_backtest_selection, reader, selection)
            bootstrap_coverage = await _load_replay_coverage(reader, selection)
            state = ArchiveMarketState()
            prime_sequence = await run_blocking(
                _prime_to_start,
                reader,
                state,
                selection,
                require_checkpoint_pairs=options.start_at_ms is not None,
            )
            _activate_bootstrap_blackouts(
                state,
                bootstrap_coverage,
                through_ms=selection.start_at_ms,
            )
            clock = ReplayClock(selection.start_at_ms, selection.end_at_ms)
            broker_rng = random.Random(_derived_seed(options.seed, "broker"))
            strategy_rng = random.Random(_derived_seed(options.seed, "strategy"))
            paper_broker = PaperBroker(
                config,
                state,
                state,
                rng=broker_rng,
                clock=clock,
                continuity_source=state,
            )
            planning_context = BotContext(
                config=config,
                broker=RejectingPlanningBroker(),
                markets=state,
                books=state,
                wallet_activity=RejectingWalletActivityClient(),
                positions=RejectingPositionClient(),
                clock=clock,
                rng=strategy_rng,
            )
            effective_start, prime_sequence = await _advance_to_replayable_start(
                reader,
                bot,
                planning_context,
                state,
                clock,
                selection,
                prime_sequence,
                coverage=bootstrap_coverage,
                explicit_start=options.start_at_ms is not None,
            )
            if effective_start != selection.start_at_ms:
                selection = replace(selection, start_at_ms=effective_start)
            coverage = await _load_replay_coverage(reader, selection)
            _activate_bootstrap_blackouts(
                state,
                coverage,
                through_ms=selection.start_at_ms,
            )
            if coverage is not None:
                selection = replace(
                    selection,
                    coverage_gap_ids=coverage.gap_ids,
                    coverage_gap_duration_ms=coverage.duration_ms,
                    coverage_gap_open_count=coverage.open_gap_count,
                )
            results_dir = options.results_dir or _default_results_dir(
                options.archive_path,
                config.name,
            )
            archive_sha256 = await run_blocking(_sha256, options.archive_path)
            artifacts = await run_blocking(
                PerformanceArtifacts,
                results_dir,
                provenance=RunProvenance(
                    kind=PerformanceRunKind.BACKTEST,
                    bot_spec=bot_spec,
                    configuration=config,
                    seed=options.seed,
                    archive_sha256=archive_sha256,
                    archive_schema_version=reader.schema_version,
                    archive_target_identity=reader.target_identity,
                ),
                selection=RunSelection(
                    session_id=selection.session_id,
                    start_ms=selection.start_at_ms,
                    end_ms=selection.end_at_ms,
                    market_slugs=selection.market_slugs,
                    replay_cutoff_sequence=selection.replay_cutoff_sequence,
                    session_integrity_status=(
                        selection.session_integrity_status
                    ),
                    uses_partial_session=selection.uses_partial_session,
                    gap_policy=selection.gap_policy.value,
                    coverage_gap_ids=selection.coverage_gap_ids,
                    coverage_gap_duration_ms=(
                        selection.coverage_gap_duration_ms
                    ),
                    coverage_gap_open_count=selection.coverage_gap_open_count,
                ),
                initial_cash_usdc=config.paper_portfolio_usdc,
                report_interval_ms=options.report_interval_ms,
                max_book_age_ms=config.event_max_age_ms,
            )
            for book in state.books.values():
                await run_blocking(artifacts.record_book, book)
            await run_blocking(
                artifacts.start,
                clock.now_ms(),
                paper_broker.portfolio,
            )
            broker = BacktestPerformanceBroker(
                paper_broker,
                clock=clock,
                artifacts=artifacts,
                portfolio=paper_broker.portfolio,
            )
            ctx = BotContext(
                config=config,
                broker=broker,
                markets=state,
                books=state,
                wallet_activity=RejectingWalletActivityClient(),
                positions=RejectingPositionClient(),
                clock=clock,
                rng=strategy_rng,
            )
            runner = BotRunner(bot, ctx, now_ms_fn=clock.now_ms)
            events = await run_blocking(
                reader.iter_events,
                start_at_ms=selection.start_at_ms,
                end_at_ms=selection.end_at_ms,
                session_id=selection.session_id,
                market_slugs=selection.market_slugs,
                allow_gaps=(
                    selection.gap_policy is BacktestGapPolicy.BLACKOUT
                ),
            )
            scheduler = ReplayScheduler(
                bot=bot,
                runner=runner,
                paper_broker=paper_broker,
                state=state,
                clock=clock,
                cursor=ReplayCursor(events, after_sequence=prime_sequence),
                artifacts=artifacts,
                coverage=coverage,
            )
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                await run_blocking(
                    artifacts.finalize,
                    status=PerformanceRunStatus.CANCELLED,
                    ended_at_ms=clock.now_ms(),
                    portfolio=paper_broker.portfolio,
                )
                raise
            except BaseException as error:
                await run_blocking(
                    artifacts.finalize,
                    status=PerformanceRunStatus.FAILED,
                    ended_at_ms=clock.now_ms(),
                    portfolio=paper_broker.portfolio,
                    error=f"{type(error).__name__}: {error}",
                )
                raise
            await run_blocking(
                artifacts.finalize,
                status=PerformanceRunStatus.COMPLETED,
                ended_at_ms=clock.now_ms(),
                portfolio=paper_broker.portfolio,
            )
            return BacktestResult(
                selection=selection,
                results_dir=Path(results_dir),
                event_count=scheduler.event_count,
                accepted_dispatch_count=scheduler.accepted_dispatch_count,
                skipped_dispatch_count=scheduler.skipped_dispatch_count,
                resolution_count=scheduler.resolution_count,
            )
        except ArchiveCoverageError as error:
            raise BacktestError(
                BacktestFailureReason.COVERAGE_GAP,
                str(error),
            ) from error
        except ArchiveFormatError as error:
            raise BacktestError(
                BacktestFailureReason.INVALID_SELECTION,
                str(error),
            ) from error
        except ArchiveIntegrityError as error:
            raise BacktestError(
                BacktestFailureReason.UNSUPPORTED_ARCHIVE,
                str(error),
            ) from error
    finally:
        await run_blocking(reader.close)


def _prime_to_start(
    reader: RecordingReader,
    state: ArchiveMarketState,
    selection: BacktestSelection,
    *,
    require_checkpoint_pairs: bool,
) -> int:
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
                selection.gap_policy is BacktestGapPolicy.BLACKOUT
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
                allow_gaps=(
                    selection.gap_policy is BacktestGapPolicy.BLACKOUT
                ),
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
                _session_start(reader, selection.session_id),
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
        # Each market's priming interval was validated above.
        # The merged scan can begin before another market's checkpoint, so a
        # set-wide gap check here would reject an otherwise clean subrange.
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
            selection.gap_policy is BacktestGapPolicy.BLACKOUT
            and isinstance(event.payload, CoverageGapPayload)
        ):
            continue
        state.apply(event)
    return prime_sequence


async def _advance_to_replayable_start(
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
    allow_blackouts = selection.gap_policy is BacktestGapPolicy.BLACKOUT
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
            _advance_bootstrap_coverage(
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
    allow_blackouts: bool = False,
) -> bool:
    now_ms = ctx.clock.now_ms()
    current = await bot.current_stream_rules(ctx, now_ms)
    next_rules = await bot.next_stream_rules(ctx, now_ms)
    if any(rule.wallet_addresses for rule in (*current, *next_rules)):
        raise BacktestError(
            BacktestFailureReason.UNSUPPORTED_INPUT,
            "wallet stream rules cannot be replayed from a market-only archive",
        )
    current_slugs = {
        slug for rule in current for slug in rule.market_slugs
    }
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


async def _load_replay_coverage(
    reader: RecordingReader,
    selection: BacktestSelection,
) -> ReplayCoverage | None:
    if selection.gap_policy is BacktestGapPolicy.STRICT:
        return None
    records = await run_blocking(
        _selected_coverage_gaps,
        reader,
        selection,
    )
    return ReplayCoverage(
        records,
        start_at_ms=selection.start_at_ms,
        end_at_ms=selection.end_at_ms,
    )


def _selected_coverage_gaps(
    reader: RecordingReader,
    selection: BacktestSelection,
) -> tuple[CoverageGapRecord, ...]:
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


def _activate_bootstrap_blackouts(
    state: ArchiveMarketState,
    coverage: ReplayCoverage | None,
    *,
    through_ms: int,
) -> None:
    if coverage is None:
        return
    for record in coverage.pop_start_records_through(through_ms):
        state.begin_blackout(record)


def _advance_bootstrap_coverage(
    state: ArchiveMarketState,
    clock: ReplayClock,
    coverage: ReplayCoverage | None,
    *,
    through_ms: int,
) -> None:
    if coverage is None:
        return
    while (
        (boundary_ms := coverage.next_boundary_at_ms) is not None
        and boundary_ms <= through_ms
    ):
        clock.move_to(boundary_ms)
        _activate_bootstrap_blackouts(
            state,
            coverage,
            through_ms=boundary_ms,
        )
        if coverage.pop_end_records_through(boundary_ms):
            state.recover_books_at(boundary_ms)


def _session_start(reader: RecordingReader, session_id: int) -> int:
    return reader.select_session(session_id).started_at_ms


def _derived_seed(seed: int, purpose: str) -> int:
    digest = hashlib.sha256(f"{seed}:{purpose}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _default_results_dir(archive_path: Path, bot_name: str) -> Path:
    safe_name = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in bot_name
    ).strip("-") or "bot"
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    suffix = time.time_ns() % 1_000_000_000
    return Path("backtest-results") / (
        f"{archive_path.stem}-{safe_name}-{timestamp}-{suffix:09d}"
    )
