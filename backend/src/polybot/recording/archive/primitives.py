"""Small validation and selection primitives for archive adapters."""

from __future__ import annotations

from polybot.framework.timestamps import require_nonnegative_timestamp_ms
from polybot.integers import validate_nonnegative_int, validate_positive_int


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _strict_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_strict_int(value: object, name: str) -> int | None:
    return None if value is None else _strict_int(value, name)


def _positive_int(value: object, name: str) -> int:
    validate_positive_int(value, name)
    return value


def _nonnegative_timestamp_ms(value: object, name: str) -> int:
    parsed = _strict_int(value, name)
    return require_nonnegative_timestamp_ms(parsed, name)


def _nonnegative_int(value: object, name: str) -> int:
    parsed = _strict_int(value, name)
    validate_nonnegative_int(parsed, name)
    return parsed
