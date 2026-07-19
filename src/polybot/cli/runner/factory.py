"""Construction of paper-runner adapters and durable runtime state."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket import AsyncPublicClient

from polybot.cli.observability.broker import ObservableBroker
from polybot.cli.observability.activity import ObserverActivitySink
from polybot.cli.observability.events import PortfolioSnapshot
from polybot.cli.observability.observer import RuntimeObserver
from polybot.execution.paper import PaperBroker
from polybot.execution.paper.idempotency import FileSourceIdempotencyStore
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.positions import PositionClient
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.wallet_activity.client import PolymarketWalletActivityClient
from polybot.polymarket.ws_market import MarketStream

from ..followed_wallets.tracker import FollowedWalletTracker
from ..resolution_state import ResolutionLedger
from ..tracked_markets import TrackedMarketRegistry
from .state import (
    FOLLOWED_WALLET_STORE_SUFFIX,
    RESOLUTION_LEDGER_SUFFIX,
    SOURCE_ID_STORE_SUFFIX,
    state_path,
)


@dataclass(slots=True)
class RuntimeComponents:
    public_client: AsyncPublicClient
    owned_client: bool
    gamma: GammaClient
    clob: ClobClient
    market_stream: MarketStream
    wallet_activity_client: PolymarketWalletActivityClient
    position_client: PositionClient
    followed_wallets: FollowedWalletTracker
    resolution_ledger: ResolutionLedger
    registry: TrackedMarketRegistry
    paper_broker: PaperBroker
    broker: ObservableBroker
    ctx: BotContext


async def create_runtime(
    config: BotConfig,
    observer: RuntimeObserver,
    *,
    client: AsyncPublicClient | None,
) -> RuntimeComponents:
    public_client = client or AsyncPublicClient()
    gamma = GammaClient(public_client)
    clob = ClobClient(public_client)
    market_stream = MarketStream(public_client)
    wallet_activity_client = PolymarketWalletActivityClient(public_client)
    position_client = PositionClient(public_client)
    source_store = FileSourceIdempotencyStore(
        state_path(config.name, SOURCE_ID_STORE_SUFFIX)
    )
    followed_wallets = await FollowedWalletTracker.create(
        state_path(config.name, FOLLOWED_WALLET_STORE_SUFFIX)
    )
    resolution_ledger = await ResolutionLedger.create(
        state_path(config.name, RESOLUTION_LEDGER_SUFFIX)
    )
    registry = TrackedMarketRegistry(
        terminal_condition_ids=resolution_ledger.resolved_condition_ids
    )
    paper_broker = PaperBroker(config, clob, gamma, source_store=source_store)
    broker = ObservableBroker(
        paper_broker,
        observer,
        lambda: PortfolioSnapshot.from_paper(paper_broker.portfolio),
    )
    return RuntimeComponents(
        public_client=public_client,
        owned_client=client is None,
        gamma=gamma,
        clob=clob,
        market_stream=market_stream,
        wallet_activity_client=wallet_activity_client,
        position_client=position_client,
        followed_wallets=followed_wallets,
        resolution_ledger=resolution_ledger,
        registry=registry,
        paper_broker=paper_broker,
        broker=broker,
        ctx=BotContext(
            config=config,
            broker=broker,
            markets=gamma,
            books=clob,
            wallet_activity=wallet_activity_client,
            positions=position_client,
            activity=ObserverActivitySink(observer),
        ),
    )
