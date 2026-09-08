from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.framework.events.prices import is_outcome_payout, is_outcome_price
from polybot.polymarket.errors import MarketDataError, MarketDataIssue


def _nested_value(source: object, *attributes: str) -> object:
    current = source
    for attribute in attributes:
        current = getattr(current, attribute, None)
    return current


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


def _optional_boolean(value: object, field: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise MarketDataError(
        MarketDataIssue.INVALID_MARKET_PARAMETERS,
        f"{field} is malformed",
    )


def _positive_decimal(value: object, field: str) -> Decimal:
    normalized = _decimal(value, field)
    if normalized <= 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be positive",
        )
    return normalized


def _optional_positive_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _positive_decimal(value, field)


def _non_negative_decimal(value: object, field: str) -> Decimal:
    normalized = _decimal(value, field)
    if normalized < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must not be negative",
        )
    return normalized


def _optional_non_negative_decimal(value: object, field: str) -> Decimal | None:
    return None if value is None else _non_negative_decimal(value, field)


def _probability(value: object, field: str) -> Decimal:
    normalized = _decimal(value, field)
    if not is_outcome_price(normalized):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be greater than zero and at most one",
        )
    return normalized


def _optional_probability(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    normalized = _decimal(value, field)
    if not is_outcome_payout(normalized):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be between zero and one",
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
            f"{field} is malformed",
        ) from error
