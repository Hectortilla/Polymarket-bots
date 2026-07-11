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
        await runner.refresh_markets()
        await runner.refresh_wallets()
        resolved = await resolve_plan_markets(runner.market_plan, gamma)
        clob.set_markets(resolved.current)
        market_stream.set_markets(resolved.current)
        streams = build_streams(
            market_stream,
            wallet_stream=WalletActivityStream(wallet_source),
            markets=resolved.current,
            wallet_addresses=runner.wallet_plan.active_addresses,
        )
        if not streams:
            raise RuntimeError(
                "the bot declared no current market or wallet subscriptions"
            )
        async for item in merge_streams(streams):
            await _dispatch_stream_event(runner, item)
    finally:
        await bot.on_stop(ctx)
        if owned_client:
            await public_client.close()


async def _dispatch_stream_event(runner: BotRunner, item: StreamEvent) -> None:
    if item.kind is StreamKind.BOOK:
        await runner.dispatch_book(item.event)
    elif item.kind is StreamKind.WALLET:
        await runner.dispatch_wallet_trade(item.event)
