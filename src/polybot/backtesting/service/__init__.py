"""Public construction and lifecycle of one deterministic archive replay."""

from __future__ import annotations

import asyncio
import random
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
    BacktestOptions,
    BacktestResult,
    BacktestSelection,
)
from polybot.backtesting.scheduler.cursor import ReplayCursor
from polybot.backtesting.scheduler.replay import ReplayScheduler
from polybot.backtesting.selection import (
    resolve_backtest_selection,
    validate_backtest_selection,
)
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig, BotMode
from polybot.framework.context import BotContext
from polybot.framework.runner import BotRunner
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
)
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.archive.errors import (
    ArchiveCoverageError,
    ArchiveFormatError,
    ArchiveIntegrityError,
    ArchiveLockedError,
    RecordingArchiveError,
)

from .coverage import (
    activate_bootstrap_blackouts,
    load_replay_coverage,
)
from .bootstrap import advance_to_replayable_start, prime_to_start
from .results import archive_sha256 as archive_fingerprint
from .results import default_results_dir, derived_seed


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
            bootstrap_coverage = await load_replay_coverage(reader, selection)
            state = ArchiveMarketState()
            prime_sequence = await run_blocking(
                prime_to_start,
                reader,
                state,
                selection,
                require_checkpoint_pairs=options.start_at_ms is not None,
            )
            activate_bootstrap_blackouts(
                state,
                bootstrap_coverage,
                through_ms=selection.start_at_ms,
            )
            clock = ReplayClock(selection.start_at_ms, selection.end_at_ms)
            broker_rng = random.Random(derived_seed(options.seed, "broker"))
            strategy_rng = random.Random(derived_seed(options.seed, "strategy"))
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
            effective_start, prime_sequence = await advance_to_replayable_start(
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
            coverage = await load_replay_coverage(reader, selection)
            activate_bootstrap_blackouts(
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
            results_dir = options.results_dir or default_results_dir(
                options.archive_path,
                config.name,
            )
            archive_sha256 = await run_blocking(
                archive_fingerprint,
                options.archive_path,
            )
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
                    gap_policy=selection.gap_policy,
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
                allow_gaps=selection.gap_policy.allows_gaps,
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
