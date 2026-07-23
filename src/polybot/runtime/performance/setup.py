"""Artifact setup for optional paper-runtime performance recording."""

from __future__ import annotations

from pathlib import Path

from polybot.async_io import run_blocking
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.contracts.files import DEFAULT_REPORT_INTERVAL_MS
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    RunProvenance,
    RunSelection,
)

from .recording import PaperPerformanceRecorder


async def create_paper_performance_recorder(
    results_dir: str | Path,
    *,
    bot_spec: str,
    config: BotConfig,
    ctx: BotContext,
    portfolio: PaperPortfolio,
    report_interval_ms: int = DEFAULT_REPORT_INTERVAL_MS,
) -> PaperPerformanceRecorder:
    """Create performance artifacts for a paper run without changing runtime IO."""
    start_ms = ctx.clock.now_ms()
    artifacts = await run_blocking(
        PerformanceArtifacts,
        results_dir,
        provenance=RunProvenance(
            kind=PerformanceRunKind.PAPER,
            bot_spec=bot_spec,
            configuration=config,
        ),
        selection=RunSelection(
            session_id=None,
            start_ms=start_ms,
            end_ms=None,
            market_slugs=configured_market_slugs(config),
        ),
        initial_cash_usdc=config.paper_portfolio_usdc,
        report_interval_ms=report_interval_ms,
        max_book_age_ms=config.event_max_age_ms,
    )
    return PaperPerformanceRecorder(
        artifacts,
        portfolio=portfolio,
        clock=ctx.clock,
    )


def configured_market_slugs(config: BotConfig) -> tuple[str, ...]:
    """Return the unique static market slugs represented by paper artifacts."""
    return tuple(
        dict.fromkeys(
            slug for rule in config.stream_rules for slug in rule.market_slugs
        )
    )
