"""Validation and normalization for official positions API payloads."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.framework.events.prices import (
    OUTCOME_PRICE_CEILING,
    OUTCOME_PRICE_FLOOR,
)
from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.errors import MarketDataError, MarketDataIssue

from .contracts import Position
from .fields import (
    POSITION_PAGE_ITEMS_ATTRIBUTE,
    POSITION_RESPONSE_AVERAGE_PRICE_ATTRIBUTE,
    POSITION_RESPONSE_CONDITION_ID_ATTRIBUTE,
    POSITION_RESPONSE_CURRENT_PRICE_ATTRIBUTE,
    POSITION_RESPONSE_MARKET_SLUG_ATTRIBUTE,
    POSITION_RESPONSE_OUTCOME_ATTRIBUTE,
    POSITION_RESPONSE_SIZE_ATTRIBUTE,
    POSITION_RESPONSE_TOKEN_ID_ATTRIBUTE,
    POSITION_RESPONSE_WALLET_ATTRIBUTE,
)


def normalize_position(
    source: object,
    *,
    requested_wallet: str,
    requested_conditions: frozenset[str] | None,
) -> Position:
    response_wallet = _optional_nonempty_text(
        getattr(source, POSITION_RESPONSE_WALLET_ATTRIBUTE, None)
    )
    token_id = _optional_nonempty_text(
        getattr(source, POSITION_RESPONSE_TOKEN_ID_ATTRIBUTE, None)
    )
    condition_id = _optional_nonempty_text(
        getattr(source, POSITION_RESPONSE_CONDITION_ID_ATTRIBUTE, None)
    )
    market_slug = _optional_nonempty_text(
        getattr(source, POSITION_RESPONSE_MARKET_SLUG_ATTRIBUTE, None)
    )
    size = getattr(source, POSITION_RESPONSE_SIZE_ATTRIBUTE, None)
    average_price = getattr(source, POSITION_RESPONSE_AVERAGE_PRICE_ATTRIBUTE, None)
    current_price = getattr(source, POSITION_RESPONSE_CURRENT_PRICE_ATTRIBUTE, None)
    raw_outcome = getattr(source, POSITION_RESPONSE_OUTCOME_ATTRIBUTE, None)
    outcome = _optional_text(raw_outcome)
    try:
        normalized_size = Decimal(str(size))
        normalized_average = _optional_position_price(average_price)
        normalized_current = _optional_position_price(current_price)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION, "position values are invalid"
        ) from error
    if (
        response_wallet is None
        or normalize_wallet_address(response_wallet) != requested_wallet
        or token_id is None
        or condition_id is None
        or market_slug is None
        or (requested_conditions is not None and condition_id not in requested_conditions)
        or (raw_outcome is not None and outcome is None)
        or not normalized_size.is_finite()
        or normalized_size <= 0
    ):
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION,
            "position identity, response scope, or values are incomplete",
        )
    return Position(
        token_id=token_id,
        size=normalized_size,
        average_price=normalized_average,
        condition_id=condition_id,
        market_slug=market_slug,
        outcome=outcome,
        current_price=normalized_current,
    )


def page_items(page: object) -> tuple[object, ...]:
    items = getattr(page, POSITION_PAGE_ITEMS_ATTRIBUTE, None)
    if not isinstance(items, (list, tuple)):
        raise MarketDataError(
            MarketDataIssue.INVALID_POSITION,
            "position page items are malformed",
        )
    return tuple(items)


def _optional_nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _optional_nonempty_text(value)


def _optional_position_price(value: object) -> Decimal | None:
    if value is None:
        return None
    price = Decimal(str(value))
    if (
        not price.is_finite()
        or not OUTCOME_PRICE_FLOOR <= price <= OUTCOME_PRICE_CEILING
    ):
        raise ValueError("position price must be finite and between zero and one")
    return price
