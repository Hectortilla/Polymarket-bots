from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from time import monotonic, time

from polybot.framework.cadence import RESOLUTION_RECONCILIATION_SECONDS
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.resolution import GAMMA_RECONCILIATION_SOURCE
from polybot.framework.events.resolutions import MarketSettlementEvent
from polybot.execution.paper import PaperBroker
from polybot.framework.runner import BotRunner
from polybot.polymarket.gamma import GammaClient
from polybot.async_io import run_blocking
from .tracked_markets import TrackedMarketRegistry
from .market_identity import validate_resolution_market_identity
from .followed_wallets.tracker import FollowedWalletTracker
from .observability.events import MarketSettled, PortfolioSnapshot
from .observability.observer import RuntimeObserver, emit_observer
from .resolution_state import ResolutionLedger

async def reconcile_resolutions(
    registry: TrackedMarketRegistry,
    gamma: GammaClient,
    *,
    interval_seconds: float = RESOLUTION_RECONCILIATION_SECONDS,
    now_ms: Callable[[], int] | None = None,
) -> AsyncIterator[MarketResolutionEvent]:
    clock = now_ms or (lambda: int(time() * 1_000))
    while True:
        try:
            markets = registry.markets
            if markets:
                refreshed = await gamma.find_many(market.slug for market in markets)
                for market in refreshed:
                    if market is not None:
                        resolution = MarketResolutionEvent.from_market(
                            market,
                            resolved_at_ms=clock(),
                            source=GAMMA_RECONCILIATION_SOURCE,
                        )
                        if resolution is not None:
                            yield resolution
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)


async def settle_resolved_markets(
    runner: BotRunner,
    *,
    registry: TrackedMarketRegistry,
    followed_wallets: FollowedWalletTracker,
    paper_broker: PaperBroker,
    resolution_ledger: ResolutionLedger,
    observer: RuntimeObserver | None,
) -> None:
    """Settle Gamma markets already marked resolved before opening streams."""

    for market in registry.markets:
        event = MarketResolutionEvent.from_market(
            market,
            resolved_at_ms=int(time() * 1_000),
            source=GAMMA_RECONCILIATION_SOURCE,
        )
        if event is not None:
            await apply_resolution(
                runner,
                event,
                registry=registry,
                followed_wallets=followed_wallets,
                paper_broker=paper_broker,
                resolution_ledger=resolution_ledger,
                observer=observer,
            )


async def apply_resolution(
    runner: BotRunner,
    event: MarketResolutionEvent,
    *,
    registry: TrackedMarketRegistry,
    followed_wallets: FollowedWalletTracker,
    paper_broker: PaperBroker,
    resolution_ledger: ResolutionLedger,
    observer: RuntimeObserver | None,
) -> MarketSettlementEvent | None:
    tracked = registry.get(event.condition_id)
    if tracked is not None:
        validate_resolution_market_identity(
            event,
            tracked.market,
            "resolution identity does not match the tracked market",
        )
    if resolution_ledger.contains(event):
        if tracked is not None:
            registry.resolve(event.condition_id)
        return None
    if tracked is None:
        return None
    paper_snapshot = _snapshot_paper_broker(paper_broker)
    followed_snapshot = followed_wallets.snapshot()
    try:
        paper_positions = await run_blocking(paper_broker.settle_market, event)
        followed_wallet_positions = await run_blocking(followed_wallets.settle, event)
        settlement = MarketSettlementEvent(
            resolution=event,
            paper_positions=paper_positions,
            followed_wallet_positions=followed_wallet_positions,
            settled_at_ms=int(time() * 1_000),
        )
        await run_blocking(resolution_ledger.record, settlement)
    except Exception:
        _restore_paper_broker(paper_broker, paper_snapshot)
        await run_blocking(followed_wallets.restore, followed_snapshot)
        raise
    registry.resolve(event.condition_id)
    if observer is not None:
        emit_observer(
            observer,
            MarketSettled(
                settlement,
                PortfolioSnapshot.from_paper(paper_broker.portfolio),
                monotonic(),
            ),
        )
    await runner.dispatch_market_resolution(event)
    return settlement


def _snapshot_paper_broker(paper_broker: PaperBroker) -> object:
    snapshot = getattr(paper_broker, "snapshot", None)
    if callable(snapshot):
        return snapshot()
    return paper_broker.portfolio.snapshot()


def _restore_paper_broker(paper_broker: PaperBroker, snapshot: object) -> None:
    restore = getattr(paper_broker, "restore", None)
    if callable(restore):
        restore(snapshot)
        return
    paper_broker.portfolio.restore(snapshot)  # type: ignore[arg-type]
