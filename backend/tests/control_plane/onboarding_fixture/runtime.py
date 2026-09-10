"""Normalized deterministic inputs; catalog, graph, broker and ownership stay real."""

import random
from time import monotonic
from unittest.mock import AsyncMock

from api.catalog.definitions import CATALOG
from polybot.cli.observability.activity import ObserverActivitySink
from polybot.cli.observability.broker import ObservableBroker
from polybot.cli.observability.events import (
    PortfolioSnapshot,
    RuntimeStarted,
    RuntimeState,
    RuntimeStateChanged,
)
from polybot.execution.paper import PaperBroker
from polybot.execution.paper.portfolio_reader import PaperPortfolioReader
from polybot.framework.clock import SystemClock
from polybot.framework.context import BotContext, WalletActivityClient
from polybot.framework.runner import BotRunner

from control_plane.onboarding_policy import FIXTURE_RANDOM_SEED

from .market_data import OnboardingMarketData
from .selection import onboarding_case
from .stream import dispatch_books


async def onboarding_runtime(run, observer, *, execution_scope):
    config = run.config.to_bot_config()
    case = onboarding_case(config)
    if case is None:
        raise ValueError("fixture execution requires one supported onboarding market")
    # Real time preserves freshness and leases; only broker jitter is seeded.
    clock = SystemClock()
    market_data = OnboardingMarketData(case, clock)
    paper = PaperBroker(
        config,
        market_data,
        market_data,
        execution_scope=execution_scope,
        clock=clock,
        rng=random.Random(FIXTURE_RANDOM_SEED),
    )
    broker = ObservableBroker(
        paper, observer, lambda: PortfolioSnapshot.from_paper(paper.portfolio)
    )
    ctx = BotContext(
        config=config,
        broker=broker,
        markets=market_data,
        books=market_data,
        wallet_activity=AsyncMock(spec=WalletActivityClient),
        portfolio=PaperPortfolioReader(paper.portfolio),
        activity=ObserverActivitySink(observer),
        clock=clock,
    )
    bot = CATALOG[run.definition_id].create_bot(config, run.config.graph)
    runner = BotRunner(bot, ctx, now_ms_fn=clock.now_ms)
    await observer.start(config)
    observer.emit(RuntimeStarted.from_config(config))
    try:
        await bot.on_start(ctx)
        observer.emit(RuntimeStateChanged(RuntimeState.RUNNING, monotonic()))
        await dispatch_books(runner, market_data, observer)
    finally:
        try:
            await bot.on_stop(ctx)
        finally:
            await observer.stop()
