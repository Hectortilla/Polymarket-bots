"""Validation and normalization helpers for recording contracts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.framework.events.prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
)


def normalize_required_text_fields(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        value = getattr(instance, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name.replace('_', ' ')} must not be empty")
        object.__setattr__(instance, name, value.strip())


def normalize_optional_text_fields(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        value = getattr(instance, name)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name.replace('_', ' ')} must not be empty")
        object.__setattr__(instance, name, value.strip())


def normalize_text_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name.replace('_', ' ')} must be a tuple")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{name.replace('_', ' ')} contains an empty value")
        stripped = item.strip()
        if stripped not in normalized:
            normalized.append(stripped)
    return tuple(normalized)


def validate_book_price(value: Decimal) -> None:
    validate_decimal(
        value,
        "book price",
        minimum=OUTCOME_PRICE_FLOOR,
        maximum=OUTCOME_PRICE_CEILING,
        minimum_inclusive=False,
    )


def validate_tick_size(value: Decimal, name: str) -> None:
    validate_decimal(
        value,
        name,
        minimum=OUTCOME_PRICE_FLOOR,
        maximum=OUTCOME_PRICE_CEILING,
        minimum_inclusive=False,
    )


def validate_decimal(
    value: Decimal,
    name: str,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    minimum_inclusive: bool = True,
) -> None:
    try:
        is_finite = isinstance(value, Decimal) and value.is_finite()
    except (AttributeError, InvalidOperation):
        is_finite = False
    if not is_finite:
        raise ValueError(f"{name} must be a finite Decimal")
    if minimum is not None:
        below_minimum = value < minimum if minimum_inclusive else value <= minimum
        if below_minimum:
            qualifier = "at least" if minimum_inclusive else "greater than"
            raise ValueError(f"{name} must be {qualifier} {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")


def validate_positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def validate_nonnegative_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def validate_bool(value: bool, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
