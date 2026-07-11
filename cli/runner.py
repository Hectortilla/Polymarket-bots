"""Paper runner lifecycle and official-client wiring."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
from time import monotonic

from polymarket import AsyncPublicClient

from bots.execution.paper import PaperBroker
from bots.execution.paper.idempotency import FileSourceIdempotencyStore
from bots.cli.observability.broker import ObservableBroker
from bots.cli.observability.events import (
    DispatchCompleted,
    PortfolioSnapshot,
    RuntimeFailed,
    RuntimeStarted,
    RuntimeState,
    RuntimeStateChanged,
    StreamReceived,
)
from bots.cli.observability.observer import (
    NullRuntimeObserver,
    RuntimeObserver,
    emit_observer,
    start_observer,
    stop_observer,
)
from bots.framework.base import BaseBot
from bots.framework.config import BotConfig, BotMode
from bots.framework.context import BotContext
from bots.framework.dispatch import DispatchOutcome
from bots.framework.runner import BotRunner
from bots.polymarket.clob import ClobClient
from bots.polymarket.gamma import GammaClient
from bots.polymarket.wallet_activity.client import WalletActivityClient
from bots.polymarket.wallet_activity.contracts import WalletTradeSource
from bots.polymarket.wallet_activity.contracts import WalletTradeSelector
from bots.polymarket.wallet_activity.stream import WalletActivityStream
from bots.polymarket.ws_market import MarketStream

from .markets import resolve_plan_markets
from .streams import StreamEvent, StreamKind, build_streams, merge_streams

BOT_STATE_DIR = Path(".bot-state")
STATE_KEY_HEX_LENGTH = 16
SOURCE_ID_STORE_SUFFIX = ".source-ids"


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
    owned_client = client is None
    public_client = client or AsyncPublicClient()
    gamma = GammaClient(public_client)
    clob = ClobClient(public_client)
    market_stream = MarketStream(public_client)
    wallet_client = WalletActivityClient(public_client)
    state_key = sha256(config.name.encode("utf-8")).hexdigest()[:STATE_KEY_HEX_LENGTH]
    source_store = FileSourceIdempotencyStore(
        BOT_STATE_DIR / f"{state_key}{SOURCE_ID_STORE_SUFFIX}"
    )
    paper_broker = PaperBroker(config, clob, gamma, source_store=source_store)
    broker = ObservableBroker(
        paper_broker,
        runtime_observer,
        lambda: PortfolioSnapshot.from_paper(paper_broker.portfolio),
    )
    ctx = BotContext(
        config=config,
        broker=broker,
        markets=gamma,
        books=clob,
        wallet_activity=wallet_client,
    )
    runner = BotRunner(bot, ctx)

    await start_observer(runtime_observer, config)
    emit_observer(runtime_observer, RuntimeStarted.from_config(config))
    emit_observer(
        runtime_observer,
        RuntimeStateChanged(RuntimeState.STARTING, monotonic()),
    )
    failed = False
    try:
        await bot.on_start(ctx)
        if hasattr(runner, "refresh_stream_plan"):
            await runner.refresh_stream_plan()
            plan = runner.stream_plan
        else:
            await runner.refresh_markets()
            await runner.refresh_wallets()
            plan = runner.market_plan
        resolved = await resolve_plan_markets(plan, gamma)
        clob.set_markets(resolved.current)
        market_stream.set_markets(resolved.current)
        selectors = (
            _compile_selectors(plan, resolved.current)
            if getattr(plan, "current", ()) and hasattr(plan.current[0], "relation")
            else ()
        )
        wallet_stream = WalletActivityStream(
            wallet_client,
            selectors,
            wallet_source,
            budget_per_10s=config.data_trades_budget_per_10s,
        )
        streams = build_streams(
            market_stream,
            wallet_stream=wallet_stream,
            markets=resolved.current,
            wallet_enabled=bool(selectors),
        )
        if not streams:
            raise RuntimeError(
                "the bot declared no current market or wallet subscriptions"
            )
        emit_observer(
            runtime_observer,
            RuntimeStateChanged(RuntimeState.RUNNING, monotonic()),
        )
        async for item in merge_streams(streams):
            emit_observer(runtime_observer, StreamReceived(item, monotonic()))
            outcome = await _dispatch_stream_event(runner, item, wallet_stream)
            emit_observer(
                runtime_observer,
                DispatchCompleted(item, outcome, monotonic()),
            )
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


async def _dispatch_stream_event(
    runner: BotRunner,
    item: StreamEvent,
    wallet_stream: WalletActivityStream,
) -> DispatchOutcome | None:
    if item.kind is StreamKind.BOOK:
        return await runner.dispatch_book(item.event)
    elif item.kind is StreamKind.WALLET:
        return await runner.dispatch_wallet_trade(item.event)
    elif item.kind is StreamKind.MARKET_HINT:
        wallet_stream.wake_market(item.event.condition_id)
    return None


def _compile_selectors(plan, markets) -> tuple[WalletTradeSelector, ...]:
    by_slug = {market.slug: market.condition_id for market in markets}
    selectors: set[WalletTradeSelector] = set()
    for rule in plan.current:
        condition_ids = tuple(by_slug[slug] for slug in rule.market_slugs)
        if rule.relation.value == "filtered":
            selectors.update(
                WalletTradeSelector(wallet=wallet, condition_ids=condition_ids)
                for wallet in rule.wallet_addresses
            )
        else:
            if condition_ids:
                selectors.add(WalletTradeSelector(condition_ids=condition_ids))
            selectors.update(WalletTradeSelector(wallet=wallet) for wallet in rule.wallet_addresses)
    return tuple(sorted(selectors, key=lambda item: (item.wallet or "", item.condition_ids)))
