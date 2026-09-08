"""Dispatch of multiplexed CLI stream events into framework contracts."""

from __future__ import annotations

from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.runner import BotRunner
from polybot.polymarket.clob import ClobClient
from polybot.polymarket.gamma import GammaClient
from polybot.polymarket.wallet_activity.stream import WalletActivityStream

from ..followed_wallets.tracker import FollowedWalletTracker
from ..resolution.settlement import ResolutionSettlementService
from ..streams.contracts import BookGapStreamEvent, StreamEvent
from ..streams.kinds import StreamKind
from ..tracked_markets import TrackedMarketRegistry
from .book_dispatch import dispatch_book
from .resolution_dispatch import dispatch_resolution
from .wallet_dispatch import dispatch_wallet_trade


async def dispatch_stream_event(
    runner: BotRunner,
    stream_event: StreamEvent,
    wallet_stream: WalletActivityStream,
    *,
    gamma: GammaClient,
    clob: ClobClient,
    registry: TrackedMarketRegistry | None = None,
    followed_wallets: FollowedWalletTracker | None = None,
    resolution_service: ResolutionSettlementService | None = None,
) -> DispatchOutcome | None:
    if isinstance(stream_event, BookGapStreamEvent):
        await runner.dispatch_book_gap(stream_event.event)
        return None
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
        if resolution_service is None:
            raise RuntimeError(
                "resolution dispatch dependencies are required for resolution events"
            )
        await dispatch_resolution(
            stream_event,
            resolution_service,
        )
    return None
