"""Configuration sanitization for durable performance reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import StrEnum


SENSITIVE_CONFIGURATION_FIELDS = frozenset(
    {
        "api_key",
        "api_passphrase",
        "api_secret",
        "funder_address",
        "private_key",
    }
)


def sanitized_configuration(configuration: object) -> dict[str, object]:
    """Return a JSON-ready configuration object with credentials omitted."""
    if is_dataclass(configuration) and not isinstance(configuration, type):
        values = {
            field.name: getattr(configuration, field.name)
            for field in fields(configuration)
        }
    elif isinstance(configuration, Mapping):
        values = dict(configuration)
    else:
        raise TypeError("performance configuration must be a dataclass or mapping")
    return {
        str(key): _json_value(value)
        for key, value in values.items()
        if str(key) not in SENSITIVE_CONFIGURATION_FIELDS
    }


def json_value(value: object) -> object:
    """Normalize a report value without converting exact decimals to floats."""
    return _json_value(value)


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("performance report decimals must be finite")
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
            if field.name not in SENSITIVE_CONFIGURATION_FIELDS
        }
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
            if str(key) not in SENSITIVE_CONFIGURATION_FIELDS
        }
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_value(item) for item in sorted(value, key=str)]
    raise TypeError(
        f"performance report value is not JSON serializable: {type(value).__name__}"
    )
