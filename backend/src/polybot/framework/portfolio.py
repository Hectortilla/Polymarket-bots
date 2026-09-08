"""Immutable own-account portfolio views for strategy reads."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    token_id: str
    size: Decimal
    average_entry_price: Decimal | None


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    available_cash: Decimal
    positions: tuple[PortfolioPosition, ...] = ()

    def position(self, token_id: str) -> PortfolioPosition:
        return next(
            (position for position in self.positions if position.token_id == token_id),
            PortfolioPosition(token_id, Decimal(0), None),
        )


class PortfolioReader(Protocol):
    def snapshot(self) -> PortfolioSnapshot: ...
