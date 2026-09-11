from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from polybot.framework.wallets import validate_wallet_address


def normalized_number(value: object, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return None
    try:
        normalized = float(value)
        return normalized if isfinite(normalized) else None
    except (TypeError, ValueError, OverflowError):
        return None


def required_identifier(candidate: Mapping[object, object], field: str) -> str | None:
    value = candidate.get(field)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalized_wallet(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return validate_wallet_address(value)
    except ValueError:
        return None
