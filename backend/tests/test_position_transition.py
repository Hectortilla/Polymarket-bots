from __future__ import annotations

from decimal import Decimal

import pytest

from polybot.framework.events import Side
from polybot.framework.position_transition import transition_signed_position


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
