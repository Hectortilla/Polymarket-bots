"""Portfolio valuation input and result contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from .valuation_status import ValuationStatus


ZERO_MARKET_VALUE = Decimal("0")


class PositionLike(Protocol):
    token_id: str
    size: Decimal
    average_entry_price: Decimal | None


class PortfolioLike(Protocol):
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal
    positions: Mapping[str, PositionLike] | tuple[PositionLike, ...]


@dataclass(frozen=True, slots=True)
class PositionValuation:
    token_id: str
    size: Decimal
    average_entry_price: Decimal | None
    executable_mark: Decimal | None
    last_executable_mark: Decimal | None
    market_value_usdc: Decimal | None
    status: ValuationStatus

    @property
    def effective_mark(self) -> Decimal | None:
        if self.executable_mark is not None:
            return self.executable_mark
        return self.last_executable_mark


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    cash_usdc: Decimal
    marked_position_value_usdc: Decimal | None
    equity_usdc: Decimal | None
    pnl_usdc: Decimal | None
    exposure_usdc: Decimal | None
    positions: tuple[PositionValuation, ...]
    status: ValuationStatus

    @property
    def is_stale(self) -> bool:
        return self.status is ValuationStatus.STALE

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @classmethod
    def unavailable(
        cls,
        cash_usdc: Decimal = ZERO_MARKET_VALUE,
    ) -> PortfolioValuation:
        return cls(
            cash_usdc=cash_usdc,
            marked_position_value_usdc=None,
            equity_usdc=None,
            pnl_usdc=None,
            exposure_usdc=None,
            positions=(),
            status=ValuationStatus.UNAVAILABLE,
        )


@dataclass(frozen=True, slots=True)
class PortfolioValuationResult:
    valuation: PortfolioValuation
    next_executable_marks: tuple[tuple[str, Decimal], ...]

    def marks(self) -> dict[str, Decimal]:
        return dict(self.next_executable_marks)
