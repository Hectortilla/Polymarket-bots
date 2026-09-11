"""Execution amount invariants shared by fill contracts and accounting."""

from decimal import Decimal


def require_nonnegative_execution_amount(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"fill {name} must be a finite nonnegative Decimal")
