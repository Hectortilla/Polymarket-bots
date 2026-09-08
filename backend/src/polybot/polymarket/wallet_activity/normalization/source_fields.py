from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite

from polybot.framework.timestamps import MILLISECONDS_PER_SECOND
from polybot.polymarket.normalization.values import normalize_text_or_none
from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
    SDK_CONDITION_ID_ATTRIBUTE,
    SDK_SIDE_ATTRIBUTE,
    SDK_SIZE_ATTRIBUTE,
    SDK_TIMESTAMP_ATTRIBUTE,
    SDK_TOKEN_ID_ATTRIBUTE,
    SDK_TRANSACTION_HASH_ATTRIBUTE,
    SDK_WALLET_ATTRIBUTE,
)

EPOCH_SECONDS_INTERPRETATION_CUTOFF = 10_000_000_000


_TRADE_FIELD_ALIASES = {
    SDK_WALLET_ATTRIBUTE: PROXY_WALLET_FIELD,
    SDK_CONDITION_ID_ATTRIBUTE: CONDITION_ID_FIELD,
    SDK_TOKEN_ID_ATTRIBUTE: ACTIVITY_TOKEN_ID_FIELD,
    SDK_TRANSACTION_HASH_ATTRIBUTE: ACTIVITY_TRANSACTION_HASH_FIELD,
    SDK_SIDE_ATTRIBUTE: ACTIVITY_SIDE_FIELD,
    SDK_SIZE_ATTRIBUTE: ACTIVITY_SIZE_FIELD,
    SDK_TIMESTAMP_ATTRIBUTE: ACTIVITY_TIMESTAMP_FIELD,
}


_MISSING_TRADE_FIELD = object()


def _get_trade_field(source: object, name: str) -> object:
    if isinstance(source, dict):
        alias = _TRADE_FIELD_ALIASES.get(name)
        primary = source.get(name, _MISSING_TRADE_FIELD)
        if alias is None or alias == name:
            return None if primary is _MISSING_TRADE_FIELD else primary
        secondary = source.get(alias, _MISSING_TRADE_FIELD)
        if primary is _MISSING_TRADE_FIELD:
            return None if secondary is _MISSING_TRADE_FIELD else secondary
        if secondary is _MISSING_TRADE_FIELD:
            return primary
        return primary if _aliases_agree(name, primary, secondary) else None
    return getattr(source, name, None)


def _has_trade_field(source: object, name: str) -> bool:
    if isinstance(source, dict):
        alias = _TRADE_FIELD_ALIASES.get(name)
        return name in source or (alias is not None and alias in source)
    return hasattr(source, name)


def _timestamp_ms(value: object) -> int | None:
    if isinstance(value, datetime):
        try:
            if value.tzinfo is None or value.utcoffset() is None:
                return None
            return int(value.timestamp() * MILLISECONDS_PER_SECOND)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (OverflowError, TypeError, ValueError):
        return None
    if not isfinite(seconds) or seconds < 0:
        return None
    return (
        int(seconds * MILLISECONDS_PER_SECOND)
        if seconds < EPOCH_SECONDS_INTERPRETATION_CUTOFF
        else int(seconds)
    )


def _decimal(value: object) -> Decimal | None:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _aliases_agree(name: str, primary: object, secondary: object) -> bool:
    first = normalize_text_or_none(primary)
    second = normalize_text_or_none(secondary)
    if name == SDK_WALLET_ATTRIBUTE:
        return (
            first is not None
            and second is not None
            and first.casefold() == second.casefold()
        )
    return first is not None and first == second


def _normalized_trade_size(size: object, shares: object) -> Decimal | None:
    """Accept one size field, or two agreeing representations of it."""
    normalized_size = _decimal(size)
    normalized_shares = _decimal(shares)
    if size is None:
        return normalized_shares
    if shares is None:
        return normalized_size
    if normalized_size is None or normalized_shares is None:
        return None
    return normalized_size if normalized_size == normalized_shares else None
