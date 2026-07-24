"""Atomic application of one normalized market-resolution event."""

from __future__ import annotations

from time import monotonic

from polybot.async_io import run_blocking
from polybot.cli.followed_wallets.tracker import FollowedWalletTracker
from polybot.cli.market_identity import MarketIdentity
from polybot.cli.observability.events import MarketSettled, PortfolioSnapshot
from polybot.cli.observability.observer import (
    RuntimeObserver,
    emit_observer_fail_open,
)
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


class ResolutionSettlementService:
    """Atomically settle resolutions across runtime state and persistence."""

    def __init__(
        self,
        runner: BotRunner,
        *,
        registry: TrackedMarketRegistry,
        followed_wallets: FollowedWalletTracker,
        paper_broker: PaperBroker,
        resolution_ledger: ResolutionLedger,
        observer: RuntimeObserver | None,
    ) -> None:
        self._runner = runner
        self._registry = registry
        self._followed_wallets = followed_wallets
        self._paper_broker = paper_broker
        self._resolution_ledger = resolution_ledger
        self._observer = observer

    async def settle_existing(self) -> None:
        """Settle Gamma markets already resolved before streams open."""

        for market in self._registry.markets:
            event = resolution_event_from_market(
                market,
                resolved_at_ms=system_now_ms(),
                source=GAMMA_RECONCILIATION_SOURCE,
            )
            if event is not None:
                await self.apply(event)

    async def apply(
        self,
        event: MarketResolutionEvent,
    ) -> MarketSettlementEvent | None:
        """Persist, publish, and dispatch an idempotent settlement atomically."""

        tracked = self._registry.get(event.condition_id)
        if tracked is not None:
            identity = MarketIdentity.from_resolution(event)
            if not identity.matches_complete_token_pair(
                tracked.market
            ) or not identity.contains_token(event.winning_token_id):
                raise ValueError(
                    "resolution identity does not match the tracked market"
                )
        if self._resolution_ledger.contains(event):
            if tracked is not None:
                self._registry.resolve(event.condition_id)
            return None
        if tracked is None:
            return None
        paper_snapshot = self._paper_broker.snapshot()
        followed_snapshot = self._followed_wallets.snapshot()
        try:
            paper_positions = await run_blocking(
                self._paper_broker.settle_market,
                event,
            )
            followed_wallet_positions = await run_blocking(
                self._followed_wallets.settle,
                event,
            )
            settlement = MarketSettlementEvent(
                resolution=event,
                paper_positions=paper_positions,
                followed_wallet_positions=followed_wallet_positions,
                settled_at_ms=system_now_ms(),
            )
            await run_blocking(self._resolution_ledger.record, settlement)
        except Exception:
            self._paper_broker.restore(paper_snapshot)
            await run_blocking(
                self._followed_wallets.restore,
                followed_snapshot,
            )
            raise
        self._registry.resolve(event.condition_id)
        if self._observer is not None:
            emit_observer_fail_open(
                self._observer,
                MarketSettled(
                    settlement,
                    PortfolioSnapshot.from_paper(self._paper_broker.portfolio),
                    monotonic(),
                ),
            )
        await self._runner.dispatch_market_resolution(event)
        return settlement
