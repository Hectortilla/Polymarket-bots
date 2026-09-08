"""Strict primitives for decoding persisted performance summaries."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation


MAX_PERSISTED_DECIMAL_ADJUSTED_EXPONENT = 308
MAX_PERSISTED_DECIMAL_DIGITS = 308


def required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"performance summary {key} must be an object")
    return value


def require_exact_keys(
    payload: Mapping[str, object],
    keys: Iterable[str],
    name: str,
) -> None:
    expected = frozenset(keys)
    if frozenset(payload) != expected:
        raise ValueError(f"performance summary {name} fields are invalid")


def required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"performance summary {key} must be text")
    return value


def optional_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"performance summary {key} must be text or null")
    return value


def required_decimal_text(payload: Mapping[str, object], key: str) -> str:
    return finite_decimal_text(required_text(payload, key), key)


def optional_decimal_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"performance summary {key} must be text or null")
    return finite_decimal_text(value, key)


def finite_decimal_text(value: str, key: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"performance summary {key} must be a finite decimal")
    try:
        decimal = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError(
            f"performance summary {key} must be a finite decimal"
        ) from error
    if not decimal.is_finite():
        raise ValueError(f"performance summary {key} must be a finite decimal")
    if (
        abs(decimal.adjusted()) > MAX_PERSISTED_DECIMAL_ADJUSTED_EXPONENT
        or len(decimal.as_tuple().digits) > MAX_PERSISTED_DECIMAL_DIGITS
    ):
        raise ValueError(f"performance summary {key} is outside renderable bounds")
    return normalized


def nonnegative_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"performance summary {key} must be nonnegative")
    return value


def optional_nonnegative_int(payload: Mapping[str, object], key: str) -> int:
    if key not in payload:
        return 0
    return nonnegative_int(payload, key)


def required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"performance summary {key} must be boolean")
    return value
