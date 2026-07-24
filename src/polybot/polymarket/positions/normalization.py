"""Validation and normalization for official positions API payloads."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from polybot.framework.events.prices import (
    is_outcome_payout,
)
from polybot.framework.wallets import normalize_wallet_address
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.normalization.values import normalize_text_or_none

from .contracts import Position
from .fields import (
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
    response_wallet = normalize_text_or_none(
        getattr(source, POSITION_RESPONSE_WALLET_ATTRIBUTE, None)
    )
    token_id = normalize_text_or_none(
        getattr(source, POSITION_RESPONSE_TOKEN_ID_ATTRIBUTE, None)
    )
    condition_id = normalize_text_or_none(
        getattr(source, POSITION_RESPONSE_CONDITION_ID_ATTRIBUTE, None)
    )
    market_slug = normalize_text_or_none(
        getattr(source, POSITION_RESPONSE_MARKET_SLUG_ATTRIBUTE, None)
    )
    size = getattr(source, POSITION_RESPONSE_SIZE_ATTRIBUTE, None)
    average_price = getattr(source, POSITION_RESPONSE_AVERAGE_PRICE_ATTRIBUTE, None)
    current_price = getattr(source, POSITION_RESPONSE_CURRENT_PRICE_ATTRIBUTE, None)
    raw_outcome = getattr(source, POSITION_RESPONSE_OUTCOME_ATTRIBUTE, None)
    outcome = normalize_text_or_none(raw_outcome)
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


def _optional_position_price(value: object) -> Decimal | None:
    if value is None:
        return None
    price = Decimal(str(value))
    if not is_outcome_payout(price):
        raise ValueError("position price must be finite and between zero and one")
    return price
