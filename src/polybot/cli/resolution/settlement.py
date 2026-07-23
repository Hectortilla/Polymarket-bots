"""Atomic application of one normalized market-resolution event."""

from __future__ import annotations

from time import monotonic

from polybot.async_io import run_blocking
from polybot.cli.followed_wallets.tracker import FollowedWalletTracker
from polybot.cli.market_identity import MarketIdentity
from polybot.cli.observability.events import MarketSettled, PortfolioSnapshot
from polybot.cli.observability.observer import RuntimeObserver, emit_observer
from polybot.cli.resolution_state.ledger import ResolutionLedger
from polybot.cli.tracked_markets import TrackedMarketRegistry
from polybot.execution.paper import PaperBroker
from polybot.framework.clock import system_now_ms
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
)
from polybot.framework.runner import BotRunner
from polybot.polymarket.resolution import (
    GAMMA_RECONCILIATION_SOURCE,
    resolution_event_from_market,
)


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
        event = resolution_event_from_market(
            market,
            resolved_at_ms=system_now_ms(),
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
    """Persist, publish, and dispatch an idempotent settlement atomically."""

    tracked = registry.get(event.condition_id)
    if tracked is not None:
        identity = MarketIdentity.from_resolution(event)
        if not identity.matches_complete_token_pair(
            tracked.market
        ) or not identity.contains_token(event.winning_token_id):
            raise ValueError("resolution identity does not match the tracked market")
    if resolution_ledger.contains(event):
        if tracked is not None:
            registry.resolve(event.condition_id)
        return None
    if tracked is None:
        return None
    paper_snapshot = paper_broker.snapshot()
    followed_snapshot = followed_wallets.snapshot()
    try:
        paper_positions = await run_blocking(paper_broker.settle_market, event)
        followed_wallet_positions = await run_blocking(followed_wallets.settle, event)
        settlement = MarketSettlementEvent(
            resolution=event,
            paper_positions=paper_positions,
            followed_wallet_positions=followed_wallet_positions,
            settled_at_ms=system_now_ms(),
        )
        await run_blocking(resolution_ledger.record, settlement)
    except Exception:
        paper_broker.restore(paper_snapshot)
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
