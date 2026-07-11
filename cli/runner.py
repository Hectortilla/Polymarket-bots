"""Paper runner lifecycle and official-client wiring."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from polymarket import AsyncPublicClient

from bots.execution.paper import PaperBroker
from bots.execution.paper.idempotency import FileSourceIdempotencyStore
from bots.framework.base import BaseBot
from bots.framework.config import BotConfig, BotMode
from bots.framework.context import BotContext
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
) -> None:
    """Run one bot using public market data and the paper broker."""
    if config.mode is BotMode.LIVE:
        raise RuntimeError("live mode is not available in the paper runner CLI")
    owned_client = client is None
    public_client = client or AsyncPublicClient()
    gamma = GammaClient(public_client)
    clob = ClobClient(public_client)
    market_stream = MarketStream(public_client)
    wallet_client = WalletActivityClient(public_client)
    state_name = sha256(config.name.encode("utf-8")).hexdigest()[:STATE_KEY_HEX_LENGTH]
    source_store = FileSourceIdempotencyStore(
        BOT_STATE_DIR / f"{state_name}{SOURCE_ID_STORE_SUFFIX}"
    )
    broker = PaperBroker(config, clob, gamma, source_store=source_store)
    ctx = BotContext(
        config=config,
        broker=broker,
        markets=gamma,
        books=clob,
        wallet_activity=wallet_client,
    )
    runner = BotRunner(bot, ctx)

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
        async for item in merge_streams(streams):
            await _dispatch_stream_event(runner, item, wallet_stream)
    finally:
        await bot.on_stop(ctx)
        if owned_client:
            await public_client.close()


async def _dispatch_stream_event(
    runner: BotRunner,
    item: StreamEvent,
    wallet_stream: WalletActivityStream,
) -> None:
    if item.kind is StreamKind.BOOK:
        await runner.dispatch_book(item.event)
    elif item.kind is StreamKind.WALLET:
        await runner.dispatch_wallet_trade(item.event)
    elif item.kind is StreamKind.MARKET_HINT:
        wallet_stream.wake_market(item.event.condition_id)


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
