"""Dashboard view-selection state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DashboardView(StrEnum):
    MARKET = "market"
    WALLET = "wallet"


@dataclass(slots=True)
class DashboardViewState:
    view: DashboardView = DashboardView.MARKET

    def toggle(self) -> DashboardView:
        self.view = (
            DashboardView.WALLET
            if self.view is DashboardView.MARKET
            else DashboardView.MARKET
        )
        return self.view
