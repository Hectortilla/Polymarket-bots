"""Terminal-only followed-wallet pagination."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.dashboard.wallets import (
    DashboardWallets,
    WalletTimelineEvent,
    wallet_market_label,
)


@dataclass(slots=True)
class DashboardWalletTimeline(DashboardWallets):
    wallet_page: int = 0

    def reset_page(self) -> None:
        self.wallet_page = 0

    def maximum_page(self, lanes_per_page: int) -> int:
        if lanes_per_page <= 0:
            return 0
        return max(0, (len(self.wallet_lanes) - 1) // lanes_per_page)

    def page(self, direction: int, lanes_per_page: int) -> bool:
        if lanes_per_page <= 0:
            return False
        maximum = self.maximum_page(lanes_per_page)
        updated = min(maximum, max(0, self.wallet_page + direction))
        if updated == self.wallet_page:
            return False
        self.wallet_page = updated
        return True

    def revalidate_page(self, lanes_per_page: int) -> bool:
        if lanes_per_page <= 0:
            return False
        maximum = self.maximum_page(lanes_per_page)
        if self.wallet_page <= maximum:
            return False
        self.wallet_page = maximum
        return True
