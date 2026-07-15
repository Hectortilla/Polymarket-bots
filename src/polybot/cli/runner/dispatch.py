"""Dispatch of multiplexed CLI stream events into framework contracts."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.execution.paper import PaperBroker
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.runner import BotRunner
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.wallet_activity.stream import WalletActivityStream

from ..followed_wallets.tracker import FollowedWalletTracker
from ..observability.observer import RuntimeObserver
from ..streams.contracts import StreamEvent, StreamKind
from ..tracked_markets import TrackedMarketRegistry
from ..resolution_state import ResolutionLedger
from .book_dispatch import dispatch_book
from .resolution_dispatch import dispatch_resolution
from .wallet_dispatch import dispatch_wallet_trade


@dataclass(frozen=True, slots=True)
class ResolutionDispatchDependencies:
    """Runtime-owned dependencies required to settle a resolution event."""

    registry: TrackedMarketRegistry
    followed_wallets: FollowedWalletTracker
    paper_broker: PaperBroker
    resolution_ledger: ResolutionLedger
    observer: RuntimeObserver | None = None


async def dispatch_stream_event(
    runner: BotRunner,
    stream_event: StreamEvent,
    wallet_stream: WalletActivityStream,
    *,
    gamma: GammaClient,
    clob: ClobClient,
    registry: TrackedMarketRegistry | None = None,
    followed_wallets: FollowedWalletTracker | None = None,
    resolution: ResolutionDispatchDependencies | None = None,
) -> DispatchOutcome | None:
    if stream_event.kind is StreamKind.BOOK:
        return await dispatch_book(runner, stream_event, followed_wallets, registry)
    if stream_event.kind is StreamKind.WALLET:
        return await dispatch_wallet_trade(
            runner,
            stream_event,
            gamma=gamma,
            clob=clob,
            registry=registry,
            followed_wallets=followed_wallets,
        )
    if stream_event.kind is StreamKind.MARKET_HINT:
        wallet_stream.wake_market(stream_event.event.condition_id)
    elif stream_event.kind is StreamKind.RESOLUTION:
        if resolution is None:
            raise RuntimeError(
                "resolution dispatch dependencies are required for resolution events"
            )
        await dispatch_resolution(
            runner,
            stream_event,
            registry=resolution.registry,
            followed_wallets=resolution.followed_wallets,
            paper_broker=resolution.paper_broker,
            resolution_ledger=resolution.resolution_ledger,
            observer=resolution.observer,
        )
    return None
