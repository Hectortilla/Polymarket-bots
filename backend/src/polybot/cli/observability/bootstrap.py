"""Bootstrap instrumentation adapters for the CLI observer boundary.

The market and wallet workflow modules own the structural ports consumed by
the bootstrap workflow; these wrappers implement those ports while emitting
progress events.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal

from polybot.cli.followed_wallets.position_contracts import FollowPosition
from polybot.cli.observability.events import (
    BootstrapPhase,
    BootstrapProgress,
)
from polybot.cli.observability.observer import (
    RuntimeObserver,
    emit_observer_fail_open,
)
from polybot.polymarket.markets import Market
from polybot.polymarket.positions.contracts import Position

from ..markets import MarketResolver
from ..tracking.wallets import FollowedWalletStore

MarketProgressReporter = Callable[[tuple[str, ...], tuple[str, ...]], None]
WalletProgressReporter = Callable[[int, int], None]


class BootstrapProgressAdapter:
    """Adds bootstrap telemetry without changing bootstrap workflow contracts."""

    def __init__(self, observer: RuntimeObserver) -> None:
        self._observer = observer
        self._requested_market_slugs: set[str] = set()
        self._loaded_market_slugs: set[str] = set()

    def begin_cycle(self) -> None:
        self._requested_market_slugs.clear()
        self._loaded_market_slugs.clear()
        self._emit(
            BootstrapProgress(
                BootstrapPhase.MARKETS,
                completed=0,
                total=0,
            )
        )

    def wrap_gamma(self, gamma: MarketResolver) -> MarketResolver:
        return MarketBootstrapProgressAdapter(gamma, self._record_market_progress)

    def wrap_followed_wallets(
        self,
        followed_wallets: FollowedWalletStore,
        total_wallets: int,
    ) -> FollowedWalletStore:
        return WalletBootstrapProgressAdapter(
            followed_wallets,
            total_wallets,
            self._record_wallet_progress,
        )

    def report_wallet_progress(self, completed: int, total: int) -> None:
        self._record_wallet_progress(completed, total)

    def _record_market_progress(
        self,
        requested: tuple[str, ...],
        loaded: tuple[str, ...],
    ) -> None:
        self._requested_market_slugs.update(requested)
        self._loaded_market_slugs.update(loaded)
        self._emit(
            BootstrapProgress(
                BootstrapPhase.MARKETS,
                completed=len(self._loaded_market_slugs),
                total=len(self._requested_market_slugs),
            )
        )

    def _record_wallet_progress(self, completed: int, total: int) -> None:
        self._emit(
            BootstrapProgress(
                BootstrapPhase.WALLETS,
                completed=completed,
                total=total,
            )
        )

    def _emit(self, event: BootstrapProgress) -> None:
        emit_observer_fail_open(self._observer, event)


class MarketBootstrapProgressAdapter:
    def __init__(
        self,
        gamma: MarketResolver,
        report_market_progress: MarketProgressReporter,
    ) -> None:
        self._gamma = gamma
        self._report_market_progress = report_market_progress

    async def find_many(self, slugs: Iterable[str]) -> tuple[Market | None, ...]:
        requested = tuple(slugs)
        if not requested:
            return await self._gamma.find_many(requested)
        self._report_market_progress(requested, ())
        resolved = await self._gamma.find_many(requested)
        self._report_market_progress(
            requested,
            self._loaded_market_slugs(requested, resolved),
        )
        return resolved

    @staticmethod
    def _loaded_market_slugs(
        requested: tuple[str, ...],
        resolved: tuple[Market | None, ...],
    ) -> tuple[str, ...]:
        return tuple(
            slug for slug, market in zip(requested, resolved) if market is not None
        )


class WalletBootstrapProgressAdapter:
    def __init__(
        self,
        followed_wallets: FollowedWalletStore,
        total_wallets: int,
        report_wallet_progress: WalletProgressReporter,
    ) -> None:
        self._followed_wallets = followed_wallets
        self._total_wallets = total_wallets
        self._completed_wallets = 0
        self._report_wallet_progress = report_wallet_progress

    def synchronize(self, wallets: tuple[str, ...]) -> tuple[str, ...]:
        new_wallets = self._followed_wallets.synchronize(wallets)
        self._completed_wallets = self._total_wallets - len(new_wallets)
        self._report_wallet_progress(self._completed_wallets, self._total_wallets)
        return new_wallets

    def bootstrap(
        self,
        wallet: str,
        positions_with_baseline_marks: tuple[tuple[Position, Decimal | None], ...],
    ) -> None:
        self._followed_wallets.bootstrap(wallet, positions_with_baseline_marks)
        self._completed_wallets += 1
        self._report_wallet_progress(self._completed_wallets, self._total_wallets)

    def open_market_slugs(self) -> tuple[str, ...]:
        return self._followed_wallets.open_market_slugs()

    def tracked_market_positions(self) -> tuple[tuple[str, FollowPosition], ...]:
        return self._followed_wallets.tracked_market_positions()
