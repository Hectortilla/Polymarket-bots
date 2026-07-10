from decimal import Decimal

import pytest

from bots.execution.paper.portfolio import PaperPosition, portfolio_after_fill
from bots.framework.events import Side


def test_nonzero_position_requires_average_price() -> None:
    with pytest.raises(ValueError, match="nonzero positions"):
        PaperPosition("token", Decimal("1"), None)


def test_portfolio_transition_is_pure() -> None:
    current = PaperPosition("token")
    cash, fees, position = portfolio_after_fill(
        cash_usdc=Decimal("100"),
        cumulative_fees_usdc=Decimal("0"),
        current=current,
        token_id="token",
        side=Side.BUY,
        filled_size=Decimal("2"),
        average_price=Decimal("0.4"),
        fee_usdc=Decimal("0.01"),
    )
    assert current == PaperPosition("token")
    assert cash == Decimal("99.19")
    assert fees == Decimal("0.01")
    assert position == PaperPosition("token", Decimal("2"), Decimal("0.4"))
