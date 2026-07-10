from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from bots.framework.events import Side

EMPTY_POSITION_SIZE = Decimal("0")
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


@dataclass(slots=True)
class PaperPortfolio:
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal = INITIAL_CUMULATIVE_FEES_USDC
    positions: dict[str, PaperPosition] = field(default_factory=dict)

    def position(self, token_id: str) -> PaperPosition:
        return self.positions.get(token_id, PaperPosition(token_id=token_id))

    def apply_fill(
        self,
        *,
        token_id: str,
        side: Side,
        filled_size: Decimal,
        average_price: Decimal,
        fee_usdc: Decimal,
    ) -> PaperPosition:
        self.cash_usdc, self.cumulative_fees_usdc, updated = portfolio_after_fill(
            cash_usdc=self.cash_usdc,
            cumulative_fees_usdc=self.cumulative_fees_usdc,
            current=self.position(token_id),
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


def position_after_fill(
    *,
    current: PaperPosition,
    token_id: str,
    side: Side,
    filled_size: Decimal,
    fill_price: Decimal,
) -> PaperPosition:
    if current.size == EMPTY_POSITION_SIZE:
        return PaperPosition(
            token_id=token_id,
            size=filled_size if side is Side.BUY else -filled_size,
            average_entry_price=fill_price,
        )
    current_average = current.required_average_entry_price()
    if current.size > EMPTY_POSITION_SIZE and side is Side.BUY:
        new_size = current.size + filled_size
        weighted_average = (
            (current.size * current_average) + (filled_size * fill_price)
        ) / new_size
        return PaperPosition(token_id, new_size, weighted_average)
    if current.size < EMPTY_POSITION_SIZE and side is Side.SELL:
        current_abs = -current.size
        new_size = current.size - filled_size
        weighted_average = (
            (current_abs * current_average) + (filled_size * fill_price)
        ) / (-new_size)
        return PaperPosition(token_id, new_size, weighted_average)
    if current.size > EMPTY_POSITION_SIZE and side is Side.SELL:
        if filled_size < current.size:
            return PaperPosition(token_id, current.size - filled_size, current_average)
        if filled_size == current.size:
            return PaperPosition(token_id)
        return PaperPosition(token_id, -(filled_size - current.size), fill_price)
    if current.size < EMPTY_POSITION_SIZE and side is Side.BUY:
        current_abs = -current.size
        if filled_size < current_abs:
            return PaperPosition(token_id, current.size + filled_size, current_average)
        if filled_size == current_abs:
            return PaperPosition(token_id)
        return PaperPosition(token_id, filled_size - current_abs, fill_price)
    raise ValueError(f"unsupported side: {side}")


def portfolio_after_fill(
    *,
    cash_usdc: Decimal,
    cumulative_fees_usdc: Decimal,
    current: PaperPosition,
    token_id: str,
    side: Side,
    filled_size: Decimal,
    average_price: Decimal,
    fee_usdc: Decimal,
) -> tuple[Decimal, Decimal, PaperPosition]:
    cash_delta = filled_size * average_price
    updated_cash = (
        cash_usdc - cash_delta - fee_usdc
        if side is Side.BUY
        else cash_usdc + cash_delta - fee_usdc
    )
    updated_position = position_after_fill(
        current=current,
        token_id=token_id,
        side=side,
        filled_size=filled_size,
        fill_price=average_price,
    )
    return updated_cash, cumulative_fees_usdc + fee_usdc, updated_position
