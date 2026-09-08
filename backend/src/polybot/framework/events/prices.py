"""Shared bounds for normalized binary-outcome prices and payouts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


OUTCOME_PRICE_FLOOR = Decimal("0")
OUTCOME_PRICE_CEILING = Decimal("1")


def is_decimal_in_unit_interval(
    value: object,
    *,
    include_zero: bool,
) -> bool:
    """Return whether a Decimal is finite and within the requested unit interval."""
    if not isinstance(value, Decimal):
        return False
    try:
        lower_bound_is_valid = (
            value >= OUTCOME_PRICE_FLOOR
            if include_zero
            else value > OUTCOME_PRICE_FLOOR
        )
        return (
            value.is_finite()
            and lower_bound_is_valid
            and value <= OUTCOME_PRICE_CEILING
        )
    except (InvalidOperation, TypeError, ValueError):
        return False


def is_outcome_price(value: object) -> bool:
    """Return whether ``value`` is a finite tradable binary-outcome price."""
    return is_decimal_in_unit_interval(value, include_zero=False)


def is_outcome_payout(value: object) -> bool:
    """Return whether ``value`` is a finite binary-outcome payout."""
    return is_decimal_in_unit_interval(value, include_zero=True)
