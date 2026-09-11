"""Typed results between replay preparation, artifacts, and execution."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from polybot.backtesting.clock import ReplayClock
from polybot.backtesting.contracts import BacktestSelection
from polybot.backtesting.coverage import ReplayCoverage
from polybot.backtesting.state import ArchiveMarketState
from polybot.execution.paper import PaperBroker
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts


@dataclass(frozen=True, slots=True)
class PreparedReplay:
    selection: BacktestSelection
    state: ArchiveMarketState
    clock: ReplayClock
    paper_broker: PaperBroker
    strategy_rng: random.Random
    prime_sequence: int
    coverage: ReplayCoverage | None


@dataclass(frozen=True, slots=True)
class StartedBacktestArtifacts:
    artifacts: PerformanceArtifacts
    results_dir: Path


@dataclass(frozen=True, slots=True)
class ReplayExecutionResult:
    event_count: int
    accepted_dispatch_count: int
    skipped_dispatch_count: int
    resolution_count: int
