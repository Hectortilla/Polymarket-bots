from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.polymarket.errors import MarketDataError, MarketDataIssue


def _nested_value(source: object, *attributes: str) -> object:
    current = source
    for attribute in attributes:
        current = getattr(current, attribute, None)
    return current


def _required_text(value: object, issue: MarketDataIssue, field: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise MarketDataError(issue, f"{field} is missing")
    return normalized


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _positive_decimal(value: object, field: str) -> Decimal:
    normalized = _decimal(value, field)
    if normalized <= 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be positive",
        )
    return normalized


def _non_negative_decimal(value: object, field: str) -> Decimal:
    normalized = _decimal(value, field)
    if normalized < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must not be negative",
        )
    return normalized


def _decimal(value: object, field: str) -> Decimal:
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
        if not normalized.is_finite():
            raise InvalidOperation
        return normalized
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} is invalid",
        ) from error
