"""Decimal serialization shared by performance result artifact formats."""

from __future__ import annotations

from decimal import Decimal


ZERO_USDC_AMOUNT = Decimal("0")


def validate_money(value: Decimal, name: str, *, positive: bool = False) -> None:
    """Require finite monetary values before serializing or using them as cash."""
    if not value.is_finite() or (positive and value <= ZERO_USDC_AMOUNT):
        requirement = "positive and finite" if positive else "finite"
        raise ValueError(f"performance {name} must be {requirement}")


def decimal_text(value: Decimal) -> str:
    """Serialize a finite decimal without losing its configured precision."""
    validate_money(value, "decimal")
    return str(value)


def optional_decimal_text(value: Decimal | None) -> str | None:
    """Serialize a nullable decimal for CSV and JSON result artifacts."""
    return None if value is None else decimal_text(value)
