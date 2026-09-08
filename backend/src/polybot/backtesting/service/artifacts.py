"""Performance artifact startup for one prepared backtest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from polybot.async_io import run_blocking
from polybot.backtesting.contracts import BacktestOptions
from polybot.framework.config.models import BotConfig
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    RunProvenance,
    RunSelection,
)
from polybot.recording.archive.reader import RecordingReader

from .results import archive_sha256, default_results_dir
from .setup import PreparedReplay


@dataclass(frozen=True, slots=True)
class StartedBacktestArtifacts:
    artifacts: PerformanceArtifacts
    results_dir: Path


async def start_backtest_artifacts(
    reader: RecordingReader,
    config: BotConfig,
    *,
    bot_spec: str,
    options: BacktestOptions,
    prepared: PreparedReplay,
) -> StartedBacktestArtifacts:
    selection = prepared.selection
    results_dir = options.results_dir or default_results_dir(
        options.archive_path,
        config.name,
    )
    archive_fingerprint = await run_blocking(
        archive_sha256,
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
            archive_sha256=archive_fingerprint,
            archive_schema_version=reader.schema_version,
            archive_target_identity=reader.target_identity,
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
        initial_cash_usdc=config.paper_portfolio_usdc,
        report_interval_ms=options.report_interval_ms,
        max_book_age_ms=config.event_max_age_ms,
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
