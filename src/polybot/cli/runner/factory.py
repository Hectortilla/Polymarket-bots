"""Construction of paper-runner adapters and per-run runtime state."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.cli.observability.broker import ObservableBroker
from polybot.cli.observability.activity import ObserverActivitySink
from polybot.cli.observability.events import PortfolioSnapshot
from polybot.cli.observability.observer import RuntimeObserver
from polybot.execution.paper import PaperBroker
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.positions.client import PositionClient
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.wallet_activity.client import PolymarketWalletActivityClient
from polybot.polymarket.ws_market import MarketStream
from polybot.polymarket.public_data.runtime import RuntimePublicData

from ..followed_wallets.tracker import FollowedWalletTracker
from ..tracked_markets import TrackedMarketRegistry


@dataclass(slots=True)
class RuntimeComponents:
    public_data: RuntimePublicData
    gamma: GammaClient
    clob: ClobClient
    market_stream: MarketStream
    wallet_activity_client: PolymarketWalletActivityClient
    position_client: PositionClient
    followed_wallets: FollowedWalletTracker
    registry: TrackedMarketRegistry
    paper_broker: PaperBroker
    broker: ObservableBroker
    ctx: BotContext


async def create_runtime(
    config: BotConfig,
    observer: RuntimeObserver,
    *,
    public_data: RuntimePublicData | None,
) -> RuntimeComponents:
    owns_public_data = public_data is None
    sources = RuntimePublicData.create() if owns_public_data else public_data
    try:
        gamma = sources.gamma
        clob = sources.clob
        market_stream = sources.market_stream
        wallet_activity_client = sources.wallet_activity_client
        position_client = sources.position_client
        followed_wallets = FollowedWalletTracker()
        registry = TrackedMarketRegistry()
        paper_broker = PaperBroker(config, clob, gamma)
        broker = ObservableBroker(
            paper_broker,
            observer,
            lambda: PortfolioSnapshot.from_paper(paper_broker.portfolio),
        )
        return RuntimeComponents(
            public_data=sources,
            gamma=gamma,
            clob=clob,
            market_stream=market_stream,
            wallet_activity_client=wallet_activity_client,
            position_client=position_client,
            followed_wallets=followed_wallets,
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
    except BaseException:
        if owns_public_data:
            await sources.close()
        raise
