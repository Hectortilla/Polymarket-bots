from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from polybot.framework.events import Side
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    SettledPosition,
    realized_resolution_pnl,
)

from .settlement import PaperSettlementCalculation

EMPTY_POSITION_SIZE = Decimal("0")
PaperPortfolioSnapshot = tuple[Decimal, Decimal, dict[str, "PaperPosition"]]
INITIAL_CUMULATIVE_FEES_USDC = Decimal("0")


def calculate_after_fill(
    *,
    cash_usdc: Decimal,
    cumulative_fees_usdc: Decimal,
    position: PaperPosition,
    side: Side,
    filled_size: Decimal,
    average_price: Decimal,
    fee_usdc: Decimal,
) -> tuple[Decimal, Decimal, PaperPosition]:
    _require_positive_fill_size(filled_size)
    cash_delta = filled_size * average_price
    updated_cash = (
        cash_usdc - cash_delta - fee_usdc
        if side is Side.BUY
        else cash_usdc + cash_delta - fee_usdc
    )
    updated_position = position.after_fill(
        side=side,
        filled_size=filled_size,
        fill_price=average_price,
    )
    return updated_cash, cumulative_fees_usdc + fee_usdc, updated_position


@dataclass(frozen=True, slots=True)
class PaperPosition:
    token_id: str
    size: Decimal = EMPTY_POSITION_SIZE
    average_entry_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.size == EMPTY_POSITION_SIZE and self.average_entry_price is not None:
            raise ValueError("zero-sized positions cannot have an average entry price")
        if self.size != EMPTY_POSITION_SIZE and self.average_entry_price is None:
            raise ValueError("nonzero positions require an average entry price")

    def required_average_entry_price(self) -> Decimal:
        if self.average_entry_price is None:
            raise ValueError("nonzero positions require an average entry price")
        return self.average_entry_price

    def after_fill(
        self,
        *,
        side: Side,
        filled_size: Decimal,
        fill_price: Decimal,
    ) -> PaperPosition:
        _require_positive_fill_size(filled_size)
        if self.size == EMPTY_POSITION_SIZE:
            return PaperPosition(
                token_id=self.token_id,
                size=filled_size if side is Side.BUY else -filled_size,
                average_entry_price=fill_price,
            )
        current_average = self.required_average_entry_price()
        if self.size > EMPTY_POSITION_SIZE and side is Side.BUY:
            new_size = self.size + filled_size
            weighted_average = (
                (self.size * current_average) + (filled_size * fill_price)
            ) / new_size
            return PaperPosition(self.token_id, new_size, weighted_average)
        if self.size < EMPTY_POSITION_SIZE and side is Side.SELL:
            current_short_size = -self.size
            new_size = self.size - filled_size
            weighted_average = (
                (current_short_size * current_average) + (filled_size * fill_price)
            ) / (-new_size)
            return PaperPosition(self.token_id, new_size, weighted_average)
        if self.size > EMPTY_POSITION_SIZE and side is Side.SELL:
            if filled_size < self.size:
                return PaperPosition(
                    self.token_id, self.size - filled_size, current_average
                )
            if filled_size == self.size:
                return PaperPosition(self.token_id)
            return PaperPosition(self.token_id, -(filled_size - self.size), fill_price)
        if self.size < EMPTY_POSITION_SIZE and side is Side.BUY:
            current_short_size = -self.size
            if filled_size < current_short_size:
                return PaperPosition(
                    self.token_id, self.size + filled_size, current_average
                )
            if filled_size == current_short_size:
                return PaperPosition(self.token_id)
            return PaperPosition(
                self.token_id, filled_size - current_short_size, fill_price
            )
        raise ValueError(f"unsupported side: {side}")


@dataclass(slots=True)
class PaperPortfolio:
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal = INITIAL_CUMULATIVE_FEES_USDC
    positions: dict[str, PaperPosition] = field(default_factory=dict)

    def position(self, token_id: str) -> PaperPosition:
        return self.positions.get(token_id, PaperPosition(token_id=token_id))

    def snapshot(self) -> PaperPortfolioSnapshot:
        return self.cash_usdc, self.cumulative_fees_usdc, self.positions.copy()

    def restore(self, snapshot: PaperPortfolioSnapshot) -> None:
        self.cash_usdc, self.cumulative_fees_usdc, positions = snapshot
        self.positions = positions.copy()

    def apply_fill(
        self,
        *,
        token_id: str,
        side: Side,
        filled_size: Decimal,
        average_price: Decimal,
        fee_usdc: Decimal,
    ) -> PaperPosition:
        self.cash_usdc, self.cumulative_fees_usdc, updated = calculate_after_fill(
            cash_usdc=self.cash_usdc,
            cumulative_fees_usdc=self.cumulative_fees_usdc,
            position=self.position(token_id),
            side=side,
            filled_size=filled_size,
            average_price=average_price,
            fee_usdc=fee_usdc,
        )
        if updated.size == EMPTY_POSITION_SIZE:
            self.positions.pop(token_id, None)
        else:
            self.positions[token_id] = updated
        return updated

    def calculate_after_fill(
        self,
        *,
        token_id: str,
        side: Side,
        filled_size: Decimal,
        average_price: Decimal,
        fee_usdc: Decimal,
    ) -> tuple[Decimal, Decimal, PaperPosition]:
        return calculate_after_fill(
            cash_usdc=self.cash_usdc,
            cumulative_fees_usdc=self.cumulative_fees_usdc,
            position=self.position(token_id),
            side=side,
            filled_size=filled_size,
            average_price=average_price,
            fee_usdc=fee_usdc,
        )

    def calculate_settlement(
        self,
        event: MarketResolutionEvent,
    ) -> PaperSettlementCalculation:
        return calculate_settlement_for_positions(self.positions, event)

    def settle_market(
        self,
        event: MarketResolutionEvent,
    ) -> tuple[SettledPosition, ...]:
        calculation = self.calculate_settlement(event)
        for token_id in calculation.settled_token_ids:
            self.positions.pop(token_id, None)
        self.cash_usdc += calculation.cash_delta
        return calculation.settled


def calculate_settlement_for_positions(
    positions: Mapping[str, PaperPosition],
    event: MarketResolutionEvent,
) -> PaperSettlementCalculation:
    settlements: list[SettledPosition] = []
    cash_delta = Decimal("0")
    settled_token_ids: set[str] = set()
    for token_id in event.token_ids:
        position = positions.get(token_id)
        if position is None:
            continue
        payout = event.payout_for(token_id)
        cash_payout = position.size * payout
        settlements.append(
            SettledPosition(
                owner="paper",
                token_id=token_id,
                size=position.size,
                payout_per_token=payout,
                cash_payout_usdc=cash_payout,
                realized_pnl_usdc=realized_resolution_pnl(
                    position.size,
                    position.required_average_entry_price(),
                    payout,
                ),
            )
        )
        cash_delta += cash_payout
        settled_token_ids.add(token_id)
    return PaperSettlementCalculation(
        settled=tuple(settlements),
        cash_delta=cash_delta,
        settled_token_ids=frozenset(settled_token_ids),
    )


def _require_positive_fill_size(filled_size: Decimal) -> None:
    if not filled_size.is_finite() or filled_size <= EMPTY_POSITION_SIZE:
        raise ValueError("filled size must be positive and finite")
