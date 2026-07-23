from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from polybot.framework.events import Side
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    SettledPosition,
    realized_resolution_pnl,
)
from polybot.framework.position_transition import transition_signed_position

from .settlement import PaperSettlementCalculation

EMPTY_POSITION_SIZE = Decimal("0")
PaperPortfolioSnapshot = tuple[Decimal, Decimal, dict[str, "PaperPosition"]]
INITIAL_CUMULATIVE_FEES_USDC = Decimal("0")


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
        transition = transition_signed_position(
            current_size=self.size,
            current_average_basis=self.average_entry_price,
            side=side,
            fill_size=filled_size,
            fill_price=fill_price,
        )
        if transition.size != EMPTY_POSITION_SIZE and transition.average_basis is None:
            raise ValueError("paper positions require a known average entry price")
        return PaperPosition(
            token_id=self.token_id,
            size=transition.size,
            average_entry_price=transition.average_basis,
        )


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
        self.cash_usdc, self.cumulative_fees_usdc, updated = self.calculate_after_fill(
            token_id=token_id,
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
        cash_delta = filled_size * average_price
        updated_cash = (
            self.cash_usdc - cash_delta - fee_usdc
            if side is Side.BUY
            else self.cash_usdc + cash_delta - fee_usdc
        )
        updated_position = self.position(token_id).after_fill(
            side=side,
            filled_size=filled_size,
            fill_price=average_price,
        )
        return updated_cash, self.cumulative_fees_usdc + fee_usdc, updated_position

    def calculate_settlement(
        self,
        event: MarketResolutionEvent,
    ) -> PaperSettlementCalculation:
        settlements: list[SettledPosition] = []
        cash_delta = EMPTY_POSITION_SIZE
        settled_token_ids: set[str] = set()
        for token_id in event.token_ids:
            position = self.positions.get(token_id)
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
            settled_positions=tuple(settlements),
            cash_delta=cash_delta,
            settled_token_ids=frozenset(settled_token_ids),
        )

    def settle_market(
        self,
        event: MarketResolutionEvent,
    ) -> tuple[SettledPosition, ...]:
        calculation = self.calculate_settlement(event)
        for token_id in calculation.settled_token_ids:
            self.positions.pop(token_id, None)
        self.cash_usdc += calculation.cash_delta
        return calculation.settled_positions
