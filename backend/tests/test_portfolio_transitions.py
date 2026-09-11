from decimal import Decimal

import pytest
from polybot.execution.paper.portfolio import PaperPortfolio, PaperPosition
from polybot.framework.events import Side


def test_nonzero_position_requires_average_price() -> None:
    with pytest.raises(ValueError, match="nonzero positions"):
        PaperPosition("token", Decimal("1"), None)


def test_portfolio_transition_is_pure() -> None:
    portfolio = PaperPortfolio(cash_usdc=Decimal("100"))
    cash, fees, position = portfolio.calculate_after_fill(
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


@pytest.mark.parametrize("fee", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 0])
def test_invalid_fee_cannot_mutate_portfolio(fee: Decimal) -> None:
    portfolio = PaperPortfolio(cash_usdc=Decimal("100"))
    before = portfolio.snapshot()
    with pytest.raises(ValueError, match="fee must be a finite nonnegative Decimal"):
        portfolio.apply_fill(
            token_id="token",
            side=Side.BUY,
            filled_size=Decimal("2"),
            average_price=Decimal("0.4"),
            fee_usdc=fee,
        )
    assert portfolio.snapshot() == before
