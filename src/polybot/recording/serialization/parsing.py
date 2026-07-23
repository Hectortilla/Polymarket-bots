"""Strict JSON value parsing shared by recording payload codecs."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from polybot.framework.events import Side
from polybot.persistence.json_codec import loads_json


def load_json_object(raw_json: str) -> dict[str, Any]:
    return require_object(load_json_value(raw_json), "payload")


def load_json_value(raw_json: str) -> object:
    if not isinstance(raw_json, str):
        raise ValueError("recording payload JSON must be text")
    try:
        return loads_json(raw_json)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("recording payload JSON is malformed") from error


def require_object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"recording {name} must be an object")
    return value


def require_exact_keys(data: dict[str, Any], keys: frozenset[str]) -> None:
    actual = frozenset(data)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise ValueError(
            f"recording payload fields are invalid; missing={missing}, extra={extra}"
        )


def require_array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"recording {name} must be an array")
    return value


def require_text_tuple(value: object, name: str) -> tuple[str, ...]:
    return tuple(require_text(item, name) for item in require_array(value, name))


def require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"recording {name} must be non-empty trimmed text")
    return value


def optional_text(value: object, name: str) -> str | None:
    return None if value is None else require_text(value, name)


def require_decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"recording {name} must be a decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"recording {name} is not a decimal") from error
    if not parsed.is_finite():
        raise ValueError(f"recording {name} must be finite")
    return parsed


def optional_decimal_from_json(value: object, name: str) -> Decimal | None:
    return None if value is None else require_decimal(value, name)


def decimal_to_json(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def require_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"recording {name} must be an integer")
    return value


def optional_integer(value: object, name: str) -> int | None:
    return None if value is None else require_integer(value, name)


def require_boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"recording {name} must be a boolean")
    return value


def optional_boolean(value: object, name: str) -> bool | None:
    return None if value is None else require_boolean(value, name)


def require_side(value: object) -> Side:
    if not isinstance(value, str):
        raise ValueError("recording side must be text")
    try:
        return Side(value)
    except ValueError as error:
        raise ValueError("recording side is invalid") from error
