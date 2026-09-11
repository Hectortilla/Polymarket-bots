"""One replay session owns selection, artifact startup, and scheduler execution."""

from __future__ import annotations

import asyncio
import random
from dataclasses import replace
from pathlib import Path

from polybot.async_io import run_blocking
from polybot.backtesting.broker import BacktestPerformanceBroker
from polybot.backtesting.clients import (
    RejectingPlanningBroker,
    RejectingPositionClient,
    RejectingWalletActivityClient,
)
from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import BacktestOptions
from polybot.backtesting.scheduler.cursor import ReplayCursor
from polybot.backtesting.scheduler.replay import ReplayScheduler
from polybot.backtesting.seeding import (
    BROKER_SEED_PURPOSE,
    STRATEGY_SEED_PURPOSE,
    derived_seed,
)
from polybot.backtesting.selection import ReplaySelectionResolver
from polybot.backtesting.selection.coverage import SelectionCoverage
from polybot.backtesting.service.priming import prime_to_start
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.execution.paper.portfolio_reader import PaperPortfolioReader
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.runner import BotRunner
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
)
from polybot.persistence.hashing import sha256_file
from polybot.recording.archive.reader import RecordingReader

from .bootstrap import advance_to_replayable_start
from .contracts import PreparedReplay, ReplayExecutionResult, StartedBacktestArtifacts
from .coverage import activate_bootstrap_blackouts, load_replay_coverage
from .results import default_results_dir


class BacktestReplay:
    def __init__(
        self,
        reader: RecordingReader,
        bot: BaseBot,
        config: BotConfig,
        options: BacktestOptions,
        *,
        bot_spec: str,
    ) -> None:
        self._reader = reader
        self._bot = bot
        self._config = config
        self._options = options
        self._bot_spec = bot_spec

    async def prepare(self) -> PreparedReplay:
        session = await run_blocking(
            self._reader.select_session, self._options.session_id
        )
        selection = await run_blocking(
            ReplaySelectionResolver(self._reader).resolve,
            session,
            self._options,
        )
        await run_blocking(SelectionCoverage(self._reader).validate_events, selection)
        bootstrap_coverage = await load_replay_coverage(self._reader, selection)
        state = ArchiveMarketState()
        prime_sequence = await run_blocking(
            prime_to_start,
            self._reader,
            state,
            selection,
            require_checkpoint_pairs=self._options.start_at_ms is not None,
        )
        activate_bootstrap_blackouts(
            state,
            bootstrap_coverage,
            through_ms=selection.start_at_ms,
        )
        clock = ReplayClock(selection.start_at_ms, selection.end_at_ms)
        paper_broker = PaperBroker(
            self._config,
            state,
            state,
            rng=random.Random(derived_seed(self._options.seed, BROKER_SEED_PURPOSE)),
            clock=clock,
            continuity_source=state,
        )
        strategy_rng = random.Random(
            derived_seed(self._options.seed, STRATEGY_SEED_PURPOSE)
        )
        planning_context = BotContext(
            config=self._config,
            broker=RejectingPlanningBroker(),
            portfolio=PaperPortfolioReader(paper_broker.portfolio),
            markets=state,
            books=state,
            wallet_activity=RejectingWalletActivityClient(),
            positions=RejectingPositionClient(),
            clock=clock,
            rng=strategy_rng,
        )
        effective_start, prime_sequence = await advance_to_replayable_start(
            self._reader,
            self._bot,
            planning_context,
            state,
            clock,
            selection,
            prime_sequence,
            coverage=bootstrap_coverage,
            explicit_start=self._options.start_at_ms is not None,
        )
        if effective_start != selection.start_at_ms:
            selection = replace(selection, start_at_ms=effective_start)
        coverage = await load_replay_coverage(self._reader, selection)
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
        return PreparedReplay(
            selection=selection,
            state=state,
            clock=clock,
            paper_broker=paper_broker,
            strategy_rng=strategy_rng,
            prime_sequence=prime_sequence,
            coverage=coverage,
        )

    async def start_artifacts(
        self, prepared: PreparedReplay
    ) -> StartedBacktestArtifacts:
        selection = prepared.selection
        results_dir = self._options.results_dir or default_results_dir(
            self._options.archive_path,
            self._config.name,
        )
        archive_fingerprint = await run_blocking(
            sha256_file,
            self._options.archive_path,
        )
        artifacts = await run_blocking(
            PerformanceArtifacts,
            results_dir,
            provenance=RunProvenance(
                kind=PerformanceRunKind.BACKTEST,
                bot_spec=self._bot_spec,
                configuration=self._config,
                seed=self._options.seed,
                archive_sha256=archive_fingerprint,
                archive_schema_version=self._reader.schema_version,
                archive_target_identity=self._reader.target_identity,
            ),
            selection=RunSelection(
                session_id=selection.session_id,
                start_ms=selection.start_at_ms,
                end_ms=selection.end_at_ms,
                market_slugs=selection.market_slugs,
                replay_cutoff_sequence=selection.replay_cutoff_sequence,
                session_integrity_status=selection.session_integrity_status,
                uses_partial_session=selection.uses_partial_session,
                gap_policy=selection.gap_policy,
                coverage_gap_ids=selection.coverage_gap_ids,
                coverage_gap_duration_ms=selection.coverage_gap_duration_ms,
                coverage_gap_open_count=selection.coverage_gap_open_count,
            ),
            initial_cash_usdc=self._config.paper_portfolio_usdc,
            report_interval_ms=self._options.report_interval_ms,
            max_book_age_ms=self._config.event_max_age_ms,
        )
        for book in prepared.state.books.values():
            await run_blocking(artifacts.record_book, book)
        await run_blocking(
            artifacts.start,
            prepared.clock.now_ms(),
            prepared.paper_broker.portfolio,
        )
        return StartedBacktestArtifacts(
            artifacts=artifacts,
            results_dir=Path(results_dir),
        )

    async def execute(
        self, prepared: PreparedReplay, artifacts: PerformanceArtifacts
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
            config=self._config,
            broker=broker,
            portfolio=PaperPortfolioReader(paper_broker.portfolio),
            markets=prepared.state,
            books=prepared.state,
            wallet_activity=RejectingWalletActivityClient(),
            positions=RejectingPositionClient(),
            clock=clock,
            rng=prepared.strategy_rng,
        )
        runner = BotRunner(self._bot, context, now_ms_fn=clock.now_ms)
        selection = prepared.selection
        events = await run_blocking(
            self._reader.iter_events,
            start_at_ms=selection.start_at_ms,
            end_at_ms=selection.end_at_ms,
            session_id=selection.session_id,
            market_slugs=selection.market_slugs,
            allow_gaps=selection.gap_policy.allows_gaps,
        )
        scheduler = ReplayScheduler(
            bot=self._bot,
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
