"""Pure signed-position accounting shared by execution and tracking."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.events import Side, require_side


ZERO_POSITION_SIZE = Decimal("0")


@dataclass(frozen=True, slots=True)
class SignedPositionTransition:
    size: Decimal
    average_basis: Decimal | None
    realized_pnl_delta: Decimal | None


def transition_signed_position(
    *,
    current_size: Decimal,
    current_average_basis: Decimal | None,
    side: Side,
    fill_size: Decimal,
    fill_price: Decimal,
) -> SignedPositionTransition:
    """Apply one validated fill to a signed position without mutating state."""
    _validate_transition_inputs(
        current_size=current_size,
        current_average_basis=current_average_basis,
        side=side,
        fill_size=fill_size,
        fill_price=fill_price,
    )
    signed_fill_size = fill_size if side is Side.BUY else -fill_size
    next_size = current_size + signed_fill_size

    if current_size == ZERO_POSITION_SIZE:
        return SignedPositionTransition(next_size, fill_price, Decimal("0"))

    if current_size * signed_fill_size > ZERO_POSITION_SIZE:
        next_basis = _weighted_basis(
            current_size,
            current_average_basis,
            signed_fill_size,
            fill_price,
            next_size,
        )
        return SignedPositionTransition(next_size, next_basis, Decimal("0"))

    closed_size = min(abs(current_size), fill_size)
    realized_delta = _realized_pnl_delta(
        current_size,
        current_average_basis,
        closed_size,
        fill_price,
    )
    if next_size == ZERO_POSITION_SIZE:
        next_basis = None
    elif current_size * next_size < ZERO_POSITION_SIZE:
        next_basis = fill_price
    else:
        next_basis = current_average_basis
    return SignedPositionTransition(next_size, next_basis, realized_delta)


def _weighted_basis(
    current_size: Decimal,
    current_average_basis: Decimal | None,
    signed_fill_size: Decimal,
    fill_price: Decimal,
    next_size: Decimal,
) -> Decimal | None:
    if current_average_basis is None:
        return None
    return (
        abs(current_size) * current_average_basis
        + abs(signed_fill_size) * fill_price
    ) / abs(next_size)


def _realized_pnl_delta(
    current_size: Decimal,
    current_average_basis: Decimal | None,
    closed_size: Decimal,
    fill_price: Decimal,
) -> Decimal | None:
    if current_average_basis is None:
        return None
    unit_pnl = (
        fill_price - current_average_basis
        if current_size > ZERO_POSITION_SIZE
        else current_average_basis - fill_price
    )
    return closed_size * unit_pnl


def _validate_transition_inputs(
    *,
    current_size: Decimal,
    current_average_basis: Decimal | None,
    side: Side,
    fill_size: Decimal,
    fill_price: Decimal,
) -> None:
    require_side(side)
    if not isinstance(current_size, Decimal) or not current_size.is_finite():
        raise ValueError("position size must be finite")
    if (
        not isinstance(fill_size, Decimal)
        or not fill_size.is_finite()
        or fill_size <= ZERO_POSITION_SIZE
    ):
        raise ValueError("filled size must be positive and finite")
    if (
        not isinstance(fill_price, Decimal)
        or not fill_price.is_finite()
        or fill_price <= ZERO_POSITION_SIZE
    ):
        raise ValueError("fill price must be positive and finite")
    if current_size == ZERO_POSITION_SIZE and current_average_basis is not None:
        raise ValueError("zero-sized positions cannot have an average basis")
    if current_average_basis is not None and (
        not isinstance(current_average_basis, Decimal)
        or not current_average_basis.is_finite()
        or current_average_basis <= ZERO_POSITION_SIZE
    ):
        raise ValueError("average basis must be positive and finite")
