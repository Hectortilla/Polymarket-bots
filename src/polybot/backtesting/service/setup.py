"""Selection and deterministic state preparation for an archive replay."""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from polybot.async_io import run_blocking
from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.clients import (
    RejectingPlanningBroker,
    RejectingPositionClient,
    RejectingWalletActivityClient,
)
from polybot.backtesting.contracts import BacktestOptions, BacktestSelection
from polybot.backtesting.selection import (
    resolve_backtest_selection,
    validate_backtest_selection,
)
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.recording.archive.reader import RecordingReader

from ..coverage import ReplayCoverage
from .bootstrap import advance_to_replayable_start, prime_to_start
from .coverage import activate_bootstrap_blackouts, load_replay_coverage
from .results import derived_seed


@dataclass(frozen=True, slots=True)
class PreparedReplay:
    selection: BacktestSelection
    state: ArchiveMarketState
    clock: ReplayClock
    paper_broker: PaperBroker
    strategy_rng: random.Random
    prime_sequence: int
    coverage: ReplayCoverage | None


async def prepare_replay(
    reader: RecordingReader,
    bot: BaseBot,
    config: BotConfig,
    options: BacktestOptions,
) -> PreparedReplay:
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
    paper_broker = PaperBroker(
        config,
        state,
        state,
        rng=random.Random(derived_seed(options.seed, "broker")),
        clock=clock,
        continuity_source=state,
    )
    strategy_rng = random.Random(derived_seed(options.seed, "strategy"))
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
    return PreparedReplay(
        selection=selection,
        state=state,
        clock=clock,
        paper_broker=paper_broker,
        strategy_rng=strategy_rng,
        prime_sequence=prime_sequence,
        coverage=coverage,
    )
