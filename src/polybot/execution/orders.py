from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


TAKER_FEE_USDC_QUANTUM = Decimal("0.00001")


def taker_fee_usdc(shares: Decimal, fee_rate: Decimal, price: Decimal) -> Decimal:
    raw_fee = shares * fee_rate * price * (Decimal("1") - price)
    return raw_fee.quantize(TAKER_FEE_USDC_QUANTUM, rounding=ROUND_HALF_UP)
