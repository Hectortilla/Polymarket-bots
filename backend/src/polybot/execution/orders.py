from __future__ import annotations

from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

TAKER_FEE_USDC_QUANTUM = Decimal("0.00001")
MINIMUM_FEE_PRECISION = 28


def taker_fee_usdc(shares: Decimal, fee_rate: Decimal, price: Decimal) -> Decimal:
    # Preserve the exact product through its one rounding boundary, independent
    # of caller precision, rounding, and traps (including concurrent tasks).
    precision = max(
        MINIMUM_FEE_PRECISION,
        sum(
            len(value.as_tuple().digits) + abs(value.as_tuple().exponent)
            for value in (shares, fee_rate, price, price, TAKER_FEE_USDC_QUANTUM)
        )
        + 1,
    )
    with localcontext(Context(prec=precision, rounding=ROUND_HALF_UP)):
        raw_fee = shares * fee_rate * price * (Decimal("1") - price)
        return raw_fee.quantize(TAKER_FEE_USDC_QUANTUM)
