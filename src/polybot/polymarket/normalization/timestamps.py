"""Timestamp normalization shared by recording adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from polybot.polymarket.errors import MarketDataError, MarketDataIssue


def datetime_to_epoch_ms(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market source timestamp is malformed",
        )
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        return int(normalized.timestamp() * 1_000)
    except (OverflowError, OSError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market source timestamp is outside the supported range",
        ) from error
