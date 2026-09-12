from __future__ import annotations

from decimal import Decimal

import pytest
from polybot.framework.events import Side
from polybot.framework.position_transition import (
    remaining_long_position_size,
    transition_signed_position,
)


def test_signed_position_transition_rejects_an_unknown_side() -> None:
    with pytest.raises(ValueError, match="side must be a Side"):
        transition_signed_position(
            current_size=Decimal("1"),
            current_average_basis=Decimal("0.50"),
            side="buy",  # type: ignore[arg-type]
            fill_size=Decimal("1"),
            fill_price=Decimal("0.60"),
        )


def test_signed_position_transition_rejects_non_decimal_fill_values() -> None:
    with pytest.raises(ValueError, match="filled size must be positive and finite"):
        transition_signed_position(
            current_size=Decimal("1"),
            current_average_basis=Decimal("0.50"),
            side=Side.BUY,
            fill_size=1,  # type: ignore[arg-type]
            fill_price=Decimal("0.60"),
        )


@pytest.mark.parametrize(
    "current,filled,expected",
    [
        ("0", "0", "0"),
        ("4", "0", "4"),
        ("4", "1.5", "2.5"),
        ("4", "4", "0"),
        ("4", "5", "0"),
    ],
)
def test_sell_reduction_never_creates_a_short(current, filled, expected):
    assert remaining_long_position_size(Decimal(current), Decimal(filled)) == Decimal(
        expected
    )


@pytest.mark.parametrize(
    "invalid", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 1, "1"]
)
@pytest.mark.parametrize("invalid_current", [False, True])
def test_sell_reduction_rejects_invalid_primitive_inputs(invalid, invalid_current):
    values = (invalid, Decimal("1")) if invalid_current else (Decimal("1"), invalid)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        remaining_long_position_size(*values)
