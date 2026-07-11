from decimal import Decimal

import pytest

from bots.execution.paper.portfolio import PaperPortfolio, PaperPosition
from bots.framework.events import Side


def test_nonzero_position_requires_average_price() -> None:
    with pytest.raises(ValueError, match="nonzero positions"):
        PaperPosition("token", Decimal("1"), None)


def test_portfolio_transition_is_pure() -> None:
    portfolio = PaperPortfolio(cash_usdc=Decimal("100"))
    cash, fees, position = portfolio.after_fill(
        token_id="token",
        side=Side.BUY,
        filled_size=Decimal("2"),
        average_price=Decimal("0.4"),
        fee_usdc=Decimal("0.01"),
    )
    assert portfolio.position("token") == PaperPosition("token")
    assert portfolio.cash_usdc == Decimal("100")
    assert portfolio.cumulative_fees_usdc == Decimal("0")
    assert cash == Decimal("99.19")
    assert fees == Decimal("0.01")
    assert position == PaperPosition("token", Decimal("2"), Decimal("0.4"))
