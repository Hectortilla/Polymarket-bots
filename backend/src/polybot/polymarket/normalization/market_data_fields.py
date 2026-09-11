from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.framework.events.prices import is_outcome_payout, is_outcome_price
from polybot.polymarket.errors import MarketDataError, MarketDataIssue


def require_text(
    value: object,
    field: str,
    *,
    issue: MarketDataIssue = MarketDataIssue.INVALID_MARKET_PARAMETERS,
) -> str:
    normalized = normalize_text_or_none(value)
    if normalized is None:
        raise MarketDataError(issue, f"{field} is missing")
    return normalized


def normalize_text_or_none(value: object) -> str | None:
    """Best-effort normalization for optional vendor display text."""
    if value is None:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def validate_optional_text(
    value: object,
    field: str,
    *,
    issue: MarketDataIssue = MarketDataIssue.INVALID_MARKET_PARAMETERS,
) -> str | None:
    """Validate optional vendor text without accepting malformed present values."""
    if value is None:
        return None
    return require_text(value, field, issue=issue)


def nested_market_value(source: object, *attributes: str) -> object:
    current = source
    for attribute in attributes:
        current = getattr(current, attribute, None)
    return current


def optional_market_boolean(value: object, field: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise MarketDataError(
        MarketDataIssue.INVALID_MARKET_PARAMETERS,
        f"{field} is malformed",
    )


def require_positive_market_decimal(value: object, field: str) -> Decimal:
    normalized = require_market_decimal(value, field)
    if normalized <= 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be positive",
        )
    return normalized


def optional_positive_market_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return require_positive_market_decimal(value, field)


def require_nonnegative_market_decimal(value: object, field: str) -> Decimal:
    normalized = require_market_decimal(value, field)
    if normalized < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must not be negative",
        )
    return normalized


def optional_nonnegative_market_decimal(value: object, field: str) -> Decimal | None:
    return None if value is None else require_nonnegative_market_decimal(value, field)


def require_outcome_price(value: object, field: str) -> Decimal:
    normalized = require_market_decimal(value, field)
    if not is_outcome_price(normalized):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be greater than zero and at most one",
        )
    return normalized


def optional_outcome_payout(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    normalized = require_market_decimal(value, field)
    if not is_outcome_payout(normalized):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be between zero and one",
        )
    return normalized


def require_market_decimal(value: object, field: str) -> Decimal:
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
        if not normalized.is_finite():
            raise InvalidOperation
        return normalized
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} is malformed",
        ) from error
