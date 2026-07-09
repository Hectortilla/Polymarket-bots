from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from bots.framework.book_validation import ZERO_DECIMAL
from bots.framework.events import Side


@dataclass(frozen=True, slots=True)
class PaperPosition:
    token_id: str
    size: Decimal = ZERO_DECIMAL
    average_entry_price: Decimal | None = None


@dataclass(slots=True)
class PaperPortfolio:
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal = ZERO_DECIMAL
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
        cash_delta = filled_size * average_price
        if side is Side.BUY:
            self.cash_usdc -= cash_delta + fee_usdc
        else:
            self.cash_usdc += cash_delta - fee_usdc
        self.cumulative_fees_usdc += fee_usdc

        updated = PaperPortfolio._update_position(
            current=self.position(token_id),
            token_id=token_id,
            side=side,
            filled_size=filled_size,
            fill_price=average_price,
        )
        if updated.size == ZERO_DECIMAL:
            self.positions.pop(token_id, None)
        else:
            self.positions[token_id] = updated
        return updated

    @staticmethod
    def _update_position(
        *,
        current: PaperPosition,
        token_id: str,
        side: Side,
        filled_size: Decimal,
        fill_price: Decimal,
    ) -> PaperPosition:
        if current.size == ZERO_DECIMAL:
            return PaperPosition(
                token_id=token_id,
                size=filled_size if side is Side.BUY else -filled_size,
                average_entry_price=fill_price,
            )

        current_average = (
            current.average_entry_price
            if current.average_entry_price is not None
            else fill_price
        )
        if current.size > ZERO_DECIMAL and side is Side.BUY:
            new_size = current.size + filled_size
            weighted_average = (
                (current.size * current_average) + (filled_size * fill_price)
            ) / new_size
            return PaperPosition(
                token_id=token_id,
                size=new_size,
                average_entry_price=weighted_average,
            )

        if current.size < ZERO_DECIMAL and side is Side.SELL:
            current_abs = -current.size
            new_size = current.size - filled_size
            weighted_average = (
                (current_abs * current_average) + (filled_size * fill_price)
            ) / (-new_size)
            return PaperPosition(
                token_id=token_id,
                size=new_size,
                average_entry_price=weighted_average,
            )

        if current.size > ZERO_DECIMAL and side is Side.SELL:
            if filled_size < current.size:
                return PaperPosition(
                    token_id=token_id,
                    size=current.size - filled_size,
                    average_entry_price=current_average,
                )
            if filled_size == current.size:
                return PaperPosition(token_id=token_id)

            flipped_size = filled_size - current.size
            return PaperPosition(
                token_id=token_id,
                size=-flipped_size,
                average_entry_price=fill_price,
            )

        if current.size < ZERO_DECIMAL and side is Side.BUY:
            current_abs = -current.size
            if filled_size < current_abs:
                return PaperPosition(
                    token_id=token_id,
                    size=current.size + filled_size,
                    average_entry_price=current_average,
                )
            if filled_size == current_abs:
                return PaperPosition(token_id=token_id)

            flipped_size = filled_size - current_abs
            return PaperPosition(
                token_id=token_id,
                size=flipped_size,
                average_entry_price=fill_price,
            )

        return PaperPosition(
            token_id=token_id,
            size=current.size,
            average_entry_price=current_average,
        )
