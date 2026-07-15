"""Paper runner lifecycle orchestration."""

from __future__ import annotations

import asyncio
from time import monotonic

from polybot.cli.observability.events import (
    DispatchCompleted,
    PortfolioSnapshot,
    RuntimeFailed,
    RuntimeStarted,
    RuntimeState,
    RuntimeStateChanged,
    StreamReceived,
)
from polybot.cli.observability.observer import (
    NullRuntimeObserver,
    RuntimeObserver,
    emit_observer,
    start_observer,
    stop_observer,
)
from polybot.cli.observability.bootstrap import (
    BootstrapProgressAdapter,
    emit_paper_position_book_bootstraps,
)
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig, BotMode
from polybot.framework.runner import BotRunner
from polybot.polymarket.wallet_activity.contracts import WalletTradeSource
from polybot.polymarket.wallet_activity.stream import WalletActivityStream

from ..markets import resolve_plan_markets
from ..resolution import reconcile_resolutions, settle_resolved_markets
from ..tracked_markets import MarketInterest
from ..tracking.paper import track_paper_positions
from ..tracking.wallets import (
    synchronize_followed_wallets,
)
from ..streams.builders import build_streams
from ..streams.merger import merge_streams
from ..streams.telemetry import StreamTelemetry
from .dispatch import ResolutionDispatchDependencies, dispatch_stream_event
from .factory import create_runtime
from .health import stream_health
from .streams import compile_selectors, refresh_runner_plan, wait_for_stream_plan_change


async def run_bot(
    bot: BaseBot,
    config: BotConfig,
    *,
    wallet_source: WalletTradeSource | None = None,
    client: AsyncPublicClient | None = None,
    observer: RuntimeObserver | None = None,
) -> None:
    """Run one bot using public market data and the paper broker."""
    if config.mode is BotMode.LIVE:
        raise RuntimeError("live mode is not available in the paper runner CLI")
    runtime_observer = observer or NullRuntimeObserver()
    runtime = await create_runtime(
        config,
        runtime_observer,
        client=client,
    )
    public_client = runtime.public_client
    gamma = runtime.gamma
    clob = runtime.clob
    market_stream = runtime.market_stream
    wallet_client = runtime.wallet_client
    position_client = runtime.position_client
    followed_wallets = runtime.followed_wallets
    resolution_ledger = runtime.resolution_ledger
    registry = runtime.registry
    paper_broker = runtime.paper_broker
    broker = runtime.broker
    ctx = runtime.ctx
    owned_client = runtime.owned_client
    runner = BotRunner(bot, ctx)
    telemetry = StreamTelemetry()
    bootstrap_progress = BootstrapProgressAdapter(runtime_observer)

    await start_observer(runtime_observer, config)
    emit_observer(runtime_observer, RuntimeStarted.from_config(config))
    emit_observer(
        runtime_observer,
        RuntimeStateChanged(RuntimeState.STARTING, monotonic()),
    )
    failed = False
    try:
        await bot.on_start(ctx)
        emit_observer(
            runtime_observer,
            RuntimeStateChanged(RuntimeState.RUNNING, monotonic()),
        )
        while True:
            plan = await refresh_runner_plan(runner, config)
            bootstrap_progress.begin_cycle()
            bootstrap_gamma = bootstrap_progress.wrap_gamma(gamma)
            resolved = await resolve_plan_markets(plan, bootstrap_gamma)
            for market in resolved.current:
                registry.add(market, MarketInterest.CONFIGURED)
            wallet_scopes = plan.wallet_discovery_scopes()
            bootstrap_followed_wallets = bootstrap_progress.wrap_followed_wallets(
                followed_wallets,
                len(wallet_scopes),
            )
            if not wallet_scopes:
                bootstrap_progress.report_wallet_progress(0, 0)
            await synchronize_followed_wallets(
                wallet_scopes,
                bootstrap_followed_wallets,
                position_client,
                bootstrap_gamma,
                clob,
                registry,
                resolved_markets=resolved.current,
            )
            await track_paper_positions(paper_broker, registry, gamma)
            await settle_resolved_markets(
                runner,
                registry=registry,
                followed_wallets=followed_wallets,
                paper_broker=paper_broker,
                resolution_ledger=resolution_ledger,
                observer=runtime_observer,
            )
            clob.set_markets(registry.markets)
            market_stream.set_markets(registry.markets)
            runner.set_runtime_market_slugs(
                frozenset(market.slug for market in registry.markets)
            )
            selectors = (
                compile_selectors(plan, resolved.current)
                if getattr(plan, "current", ()) and hasattr(plan.current[0], "relation")
                else ()
            )
            wallet_stream = WalletActivityStream(
                wallet_client,
                selectors,
                wallet_source,
                budget_per_10s=config.data_trades_budget_per_10s,
                max_trade_age_ms=config.event_max_age_ms,
            )
            streams = build_streams(
                market_stream,
                wallet_stream=wallet_stream,
                markets=registry.markets,
                wallet_enabled=any(rule.wallet_addresses for rule in plan.current),
                resolution_stream=(
                    reconcile_resolutions(registry, gamma) if registry.markets else None
                ),
            )
            if not streams:
                if resolved.current and not registry.markets:
                    return
                raise RuntimeError(
                    "the bot declared no current market or wallet subscriptions"
                )

            stream_events = merge_streams(streams, telemetry=telemetry)
            next_event = asyncio.create_task(anext(stream_events))
            position_book_bootstrap = asyncio.create_task(
                emit_paper_position_book_bootstraps(
                    paper_broker,
                    clob,
                    runtime_observer,
                )
            )
            plan_change = (
                asyncio.create_task(wait_for_stream_plan_change(runner, plan))
                if hasattr(runner, "refresh_stream_plan")
                else None
            )
            registry_change = asyncio.create_task(
                registry.wait_for_change(registry.revision)
            )
            try:
                while True:
                    waiting = {next_event, registry_change}
                    if plan_change is not None:
                        waiting.add(plan_change)
                    done, _ = await asyncio.wait(
                        waiting,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if plan_change in done:
                        plan_change.result()
                        # Rebuild the union for the newly active plan while
                        # retaining every unresolved registry entry.
                        break
                    if registry_change in done:
                        registry_change.result()
                        break
                    try:
                        stream_event = next_event.result()
                    except StopAsyncIteration:
                        return
                    emit_observer(
                        runtime_observer, StreamReceived(stream_event, monotonic())
                    )
                    outcome = await dispatch_stream_event(
                        runner,
                        stream_event,
                        wallet_stream,
                        gamma=gamma,
                        clob=clob,
                        registry=registry,
                        followed_wallets=followed_wallets,
                        resolution=ResolutionDispatchDependencies(
                            registry=registry,
                            followed_wallets=followed_wallets,
                            paper_broker=paper_broker,
                            resolution_ledger=resolution_ledger,
                            observer=runtime_observer,
                        ),
                    )
                    await track_paper_positions(paper_broker, registry, gamma)
                    emit_observer(
                        runtime_observer,
                        DispatchCompleted(stream_event, outcome, monotonic()),
                    )
                    emit_observer(
                        runtime_observer,
                        stream_health(stream_event, outcome, telemetry),
                    )
                    next_event = asyncio.create_task(anext(stream_events))
            finally:
                next_event.cancel()
                position_book_bootstrap.cancel()
                if plan_change is not None:
                    plan_change.cancel()
                registry_change.cancel()
                await asyncio.gather(
                    next_event,
                    registry_change,
                    position_book_bootstrap,
                    *(() if plan_change is None else (plan_change,)),
                    return_exceptions=True,
                )
                await stream_events.aclose()
                del (
                    streams,
                    stream_events,
                    next_event,
                    registry_change,
                    position_book_bootstrap,
                )
                if plan_change is not None:
                    del plan_change
    except BaseException as error:
        if not isinstance(error, asyncio.CancelledError):
            failed = True
            emit_observer(
                runtime_observer,
                RuntimeFailed(f"{type(error).__name__}: {error}", monotonic()),
            )
        raise
    finally:
        if not failed:
            emit_observer(
                runtime_observer,
                RuntimeStateChanged(RuntimeState.STOPPING, monotonic()),
            )
        try:
            try:
                await bot.on_stop(ctx)
            finally:
                if owned_client:
                    await public_client.close()
        except BaseException as error:
            failed = True
            if not isinstance(error, asyncio.CancelledError):
                emit_observer(
                    runtime_observer,
                    RuntimeFailed(f"{type(error).__name__}: {error}", monotonic()),
                )
            raise
        finally:
            if not failed:
                emit_observer(
                    runtime_observer,
                    RuntimeStateChanged(RuntimeState.STOPPED, monotonic()),
                )
            await stop_observer(runtime_observer)
