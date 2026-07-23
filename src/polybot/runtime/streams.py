"""Plan refresh, stream construction, and event dispatch for a paper runtime."""

from __future__ import annotations

import asyncio
from time import monotonic

from polybot.cli.markets import resolve_plan_markets
from polybot.cli.observability.bootstrap import (
    BootstrapProgressAdapter,
    emit_paper_position_book_bootstraps,
)
from polybot.cli.observability.events import DispatchCompleted, StreamReceived
from polybot.cli.observability.observer import RuntimeObserver, emit_observer
from polybot.cli.resolution.reconciliation import reconcile_resolutions
from polybot.cli.resolution.settlement import settle_resolved_markets
from polybot.cli.runner.dispatch import (
    ResolutionDispatchDependencies,
    dispatch_stream_event,
)
from polybot.cli.runner.factory import RuntimeComponents
from polybot.cli.runner.health import stream_health
from polybot.cli.runner.streams import (
    compile_selectors,
    refresh_runner_plan,
    wait_for_stream_plan_change,
)
from polybot.cli.streams.builders import build_streams
from polybot.cli.streams.merger import merge_streams
from polybot.cli.streams.telemetry import StreamTelemetry
from polybot.cli.tracked_markets import MarketInterest
from polybot.cli.tracking.paper import track_paper_positions
from polybot.cli.tracking.wallets import synchronize_followed_wallets
from polybot.framework.config.models import BotConfig
from polybot.framework.runner import BotRunner
from polybot.polymarket.wallet_activity.contracts import WalletTradeSource
from polybot.polymarket.wallet_activity.stream import WalletActivityStream


async def run_runtime_streams(
    runner: BotRunner,
    config: BotConfig,
    runtime: RuntimeComponents,
    *,
    wallet_source: WalletTradeSource | None,
    observer: RuntimeObserver,
) -> None:
    """Refresh dynamic subscriptions and dispatch events until the run ends."""
    telemetry = StreamTelemetry()
    bootstrap_progress = BootstrapProgressAdapter(observer)
    while True:
        plan = await refresh_runner_plan(runner)
        bootstrap_progress.begin_cycle()
        bootstrap_gamma = bootstrap_progress.wrap_gamma(runtime.gamma)
        resolved = await resolve_plan_markets(plan, bootstrap_gamma)
        for market in resolved.current:
            runtime.registry.add(market, MarketInterest.CONFIGURED)
        wallet_scopes = plan.wallet_discovery_scopes()
        bootstrap_followed_wallets = bootstrap_progress.wrap_followed_wallets(
            runtime.followed_wallets,
            len(wallet_scopes),
        )
        if not wallet_scopes:
            bootstrap_progress.report_wallet_progress(0, 0)
        await synchronize_followed_wallets(
            wallet_scopes,
            bootstrap_followed_wallets,
            runtime.position_client,
            bootstrap_gamma,
            runtime.clob,
            runtime.registry,
            resolved_markets=resolved.current,
        )
        await track_paper_positions(
            runtime.paper_broker,
            runtime.registry,
            runtime.gamma,
        )
        await settle_resolved_markets(
            runner,
            registry=runtime.registry,
            followed_wallets=runtime.followed_wallets,
            paper_broker=runtime.paper_broker,
            resolution_ledger=runtime.resolution_ledger,
            observer=observer,
        )
        runtime.clob.set_markets(runtime.registry.markets)
        runtime.market_stream.set_markets(runtime.registry.markets)
        runner.set_runtime_market_slugs(
            frozenset(market.slug for market in runtime.registry.markets)
        )
        selectors = compile_selectors(plan, resolved.current)
        wallet_stream = WalletActivityStream(
            runtime.wallet_activity_client,
            selectors,
            source=wallet_source,
            budget_per_10s=config.data_trades_budget_per_10s,
            max_trade_age_ms=config.event_max_age_ms,
        )
        streams = build_streams(
            runtime.market_stream,
            wallet_stream=wallet_stream,
            markets=runtime.registry.markets,
            wallet_enabled=any(rule.wallet_addresses for rule in plan.current),
            resolution_stream=(
                reconcile_resolutions(runtime.registry, runtime.gamma)
                if runtime.registry.markets
                else None
            ),
        )
        if not streams:
            if resolved.current and not runtime.registry.markets:
                return
            raise RuntimeError(
                "the bot declared no current market or wallet subscriptions"
            )

        stream_events = merge_streams(streams, telemetry=telemetry)
        next_event = asyncio.create_task(anext(stream_events))
        position_book_bootstrap = asyncio.create_task(
            emit_paper_position_book_bootstraps(
                runtime.paper_broker,
                runtime.clob,
                observer,
            )
        )
        plan_change = asyncio.create_task(wait_for_stream_plan_change(runner, plan))
        registry_change = asyncio.create_task(
            runtime.registry.wait_for_change(runtime.registry.revision)
        )
        try:
            while True:
                waiting = {next_event, plan_change, registry_change}
                done, _ = await asyncio.wait(
                    waiting,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if plan_change in done:
                    plan_change.result()
                    # Rebuild active subscriptions while retaining unresolved markets.
                    break
                if registry_change in done:
                    registry_change.result()
                    break
                try:
                    stream_event = next_event.result()
                except StopAsyncIteration:
                    return
                emit_observer(observer, StreamReceived(stream_event, monotonic()))
                outcome = await dispatch_stream_event(
                    runner,
                    stream_event,
                    wallet_stream,
                    gamma=runtime.gamma,
                    clob=runtime.clob,
                    registry=runtime.registry,
                    followed_wallets=runtime.followed_wallets,
                    resolution=ResolutionDispatchDependencies(
                        registry=runtime.registry,
                        followed_wallets=runtime.followed_wallets,
                        paper_broker=runtime.paper_broker,
                        resolution_ledger=runtime.resolution_ledger,
                        observer=observer,
                    ),
                )
                await track_paper_positions(
                    runtime.paper_broker,
                    runtime.registry,
                    runtime.gamma,
                )
                emit_observer(
                    observer,
                    DispatchCompleted(stream_event, outcome, monotonic()),
                )
                emit_observer(
                    observer,
                    stream_health(stream_event, outcome, telemetry),
                )
                next_event = asyncio.create_task(anext(stream_events))
        finally:
            next_event.cancel()
            position_book_bootstrap.cancel()
            plan_change.cancel()
            registry_change.cancel()
            await asyncio.gather(
                next_event,
                plan_change,
                registry_change,
                position_book_bootstrap,
                return_exceptions=True,
            )
            await stream_events.aclose()
