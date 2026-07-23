"""Timestamp normalization shared by recording adapters."""

from __future__ import annotations

from datetime import datetime

from polybot.polymarket.errors import MarketDataError, MarketDataIssue


def datetime_to_epoch_ms(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market source timestamp is malformed",
        )
    try:
        offset = value.utcoffset()
    except (OverflowError, OSError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market source timestamp is outside the supported range",
        ) from error
    if value.tzinfo is None or offset is None:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market source timestamp must include a UTC offset",
        )
    try:
        timestamp_ms = int(value.timestamp() * 1_000)
    except (OverflowError, OSError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market source timestamp is outside the supported range",
        ) from error
    if timestamp_ms < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market source timestamp must not be negative",
        )
    return timestamp_ms
