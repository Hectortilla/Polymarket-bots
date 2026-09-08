from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from polymarket.models.gamma.market import Market as SdkMarket

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import (
    Market,
    MarketOutcome,
)
from polybot.polymarket.resolution_status import FINAL_RESOLUTION_STATUSES
from polybot.framework.events.resolutions import (
    LOSING_PAYOUT_PER_TOKEN,
    WINNING_PAYOUT_PER_TOKEN,
)

from .values import (
    _nested_value,
    _non_negative_decimal,
    _optional_boolean,
    _optional_positive_decimal,
    require_text,
)


class SdkMarketField(StrEnum):
    CONDITION_ID = "condition_id"
    SLUG = "slug"
    QUESTION = "question"
    OUTCOMES = "outcomes"
    TOKEN_ID = "token_id"
    LABEL = "label"
    PRICE = "price"
    TRADING = "trading"
    MINIMUM_TICK_SIZE = "minimum_tick_size"
    MINIMUM_ORDER_SIZE = "minimum_order_size"
    STATE = "state"
    NEG_RISK = "neg_risk"
    FEES_ENABLED = "fees_enabled"
    FEE_SCHEDULE = "fee_schedule"
    RATE = "rate"
    RESOLUTION = "resolution"
    UMA_RESOLUTION_STATUS = "uma_resolution_status"
    CLOSED = "closed"
    ACTIVE = "active"
    ACCEPTING_ORDERS = "accepting_orders"
    ENABLE_ORDER_BOOK = "enable_order_book"


class SdkOutcomeSelector(StrEnum):
    YES = "yes"
    NO = "no"


def normalize_market(source: SdkMarket) -> Market:
    condition_id = require_text(
        _nested_value(source, SdkMarketField.CONDITION_ID),
        "market condition ID",
        issue=MarketDataIssue.MISSING_CONDITION_ID,
    )
    slug = require_text(
        _nested_value(source, SdkMarketField.SLUG),
        "market slug",
        issue=MarketDataIssue.MISSING_MARKET_SLUG,
    )
    question = require_text(
        _nested_value(source, SdkMarketField.QUESTION),
        "market question",
        issue=MarketDataIssue.MISSING_QUESTION,
    )
    first_token_id = require_text(
        _nested_value(
            source,
            SdkMarketField.OUTCOMES,
            SdkOutcomeSelector.YES,
            SdkMarketField.TOKEN_ID,
        ),
        "first outcome token ID",
        issue=MarketDataIssue.MISSING_TOKEN_ID,
    )
    second_token_id = require_text(
        _nested_value(
            source,
            SdkMarketField.OUTCOMES,
            SdkOutcomeSelector.NO,
            SdkMarketField.TOKEN_ID,
        ),
        "second outcome token ID",
        issue=MarketDataIssue.MISSING_TOKEN_ID,
    )
    first_label = require_text(
        _nested_value(
            source,
            SdkMarketField.OUTCOMES,
            SdkOutcomeSelector.YES,
            SdkMarketField.LABEL,
        ),
        "first outcome label",
        issue=MarketDataIssue.INVALID_MARKET_PARAMETERS,
    )
    second_label = require_text(
        _nested_value(
            source,
            SdkMarketField.OUTCOMES,
            SdkOutcomeSelector.NO,
            SdkMarketField.LABEL,
        ),
        "second outcome label",
        issue=MarketDataIssue.INVALID_MARKET_PARAMETERS,
    )
    if first_token_id == second_token_id:
        raise MarketDataError(
            MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
            "market outcomes must have distinct token IDs",
        )
    minimum_tick_size = _optional_positive_decimal(
        _nested_value(
            source,
            SdkMarketField.TRADING,
            SdkMarketField.MINIMUM_TICK_SIZE,
        ),
        "minimum tick size",
    )
    minimum_order_size = _optional_positive_decimal(
        _nested_value(
            source,
            SdkMarketField.TRADING,
            SdkMarketField.MINIMUM_ORDER_SIZE,
        ),
        "minimum order size",
    )
    active = _optional_boolean(
        _nested_value(source, SdkMarketField.STATE, SdkMarketField.ACTIVE),
        "market active state",
    )
    closed = _optional_boolean(
        _nested_value(source, SdkMarketField.STATE, SdkMarketField.CLOSED),
        "market closed state",
    )
    order_book_enabled = _optional_boolean(
        _nested_value(
            source,
            SdkMarketField.STATE,
            SdkMarketField.ENABLE_ORDER_BOOK,
        ),
        "market order-book state",
    )
    accepting_orders = _optional_boolean(
        _nested_value(
            source,
            SdkMarketField.STATE,
            SdkMarketField.ACCEPTING_ORDERS,
        ),
        "market order-acceptance state",
    )
    neg_risk = _nested_value(
        source,
        SdkMarketField.STATE,
        SdkMarketField.NEG_RISK,
    )
    if not isinstance(neg_risk, bool):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market negative-risk flag is missing",
        )

    fees_enabled = _nested_value(
        source,
        SdkMarketField.TRADING,
        SdkMarketField.FEES_ENABLED,
    )
    if not isinstance(fees_enabled, bool):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market fee-enabled flag is missing",
        )

    fee_rate = Decimal("0")
    if fees_enabled:
        fee_schedule = _nested_value(
            source,
            SdkMarketField.TRADING,
            SdkMarketField.FEE_SCHEDULE,
        )
        if fee_schedule is None:
            raise MarketDataError(
                MarketDataIssue.INVALID_MARKET_PARAMETERS,
                "fee-enabled market has no fee schedule",
            )
        fee_rate = _non_negative_decimal(
            _nested_value(fee_schedule, SdkMarketField.RATE),
            "fee rate",
        )

    resolved, winning_token_id, winning_outcome = _resolved_outcome_from_source(
        source,
        closed=closed,
        first_token_id=first_token_id,
        first_label=first_label,
        second_token_id=second_token_id,
        second_label=second_label,
    )

    return Market(
        condition_id=condition_id,
        slug=slug,
        question=question,
        minimum_tick_size=minimum_tick_size,
        minimum_order_size=minimum_order_size,
        neg_risk=neg_risk,
        fee_rate=fee_rate,
        outcomes=(
            MarketOutcome(first_label, first_token_id),
            MarketOutcome(second_label, second_token_id),
        ),
        resolved=resolved,
        winning_token_id=winning_token_id,
        winning_outcome=winning_outcome,
        active=active,
        closed=closed,
        order_book_enabled=order_book_enabled,
        accepting_orders=accepting_orders,
    )


def _resolved_outcome_from_source(
    source: SdkMarket,
    *,
    closed: bool | None,
    first_token_id: str,
    first_label: str,
    second_token_id: str,
    second_label: str,
) -> tuple[bool, str | None, str | None]:
    """Interpret Gamma settlement fields only when they identify one winner."""
    first_price = _nested_value(
        source,
        SdkMarketField.OUTCOMES,
        SdkOutcomeSelector.YES,
        SdkMarketField.PRICE,
    )
    second_price = _nested_value(
        source,
        SdkMarketField.OUTCOMES,
        SdkOutcomeSelector.NO,
        SdkMarketField.PRICE,
    )
    resolution_status = _nested_value(
        source,
        SdkMarketField.RESOLUTION,
        SdkMarketField.UMA_RESOLUTION_STATUS,
    )
    status_value = getattr(resolution_status, "value", resolution_status)
    normalized_status = (
        status_value.strip().casefold() if isinstance(status_value, str) else status_value
    )
    resolution_reported = (
        normalized_status in FINAL_RESOLUTION_STATUSES or closed is True
    )
    if not resolution_reported:
        return False, None, None
    if (
        first_price == WINNING_PAYOUT_PER_TOKEN
        and second_price == LOSING_PAYOUT_PER_TOKEN
    ):
        return True, first_token_id, first_label
    if (
        second_price == WINNING_PAYOUT_PER_TOKEN
        and first_price == LOSING_PAYOUT_PER_TOKEN
    ):
        return True, second_token_id, second_label
    return False, None, None
