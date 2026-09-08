"""Storage contract for followed-wallet accounting and bootstrap."""

from decimal import Decimal
from typing import Protocol

from polybot.polymarket.positions.contracts import Position

from .position_contracts import FollowPosition


class FollowedWalletStore(Protocol):
    def synchronize(self, wallets: tuple[str, ...]) -> tuple[str, ...]: ...

    def bootstrap(
        self,
        wallet: str,
        positions_with_baseline_marks: tuple[tuple[Position, Decimal | None], ...],
    ) -> None: ...

    def open_market_slugs(self) -> tuple[str, ...]: ...

    def tracked_market_positions(self) -> tuple[tuple[str, FollowPosition], ...]: ...
