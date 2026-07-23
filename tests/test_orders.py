from decimal import Decimal

from polybot.execution.orders import TAKER_FEE_USDC_QUANTUM, taker_fee_usdc


def test_taker_fee_is_symmetric_around_half_probability() -> None:
    low = taker_fee_usdc(Decimal("100"), Decimal("0.05"), Decimal("0.30"))
    high = taker_fee_usdc(Decimal("100"), Decimal("0.05"), Decimal("0.70"))

    assert low == high == Decimal("1.05000")


def test_taker_fee_rounds_to_five_decimals() -> None:
    fee = taker_fee_usdc(Decimal("0.001"), Decimal("0.05"), Decimal("0.50"))

    assert fee == TAKER_FEE_USDC_QUANTUM
