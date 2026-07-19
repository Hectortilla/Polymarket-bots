from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from polymarket.models.gamma.market import Market as SdkMarket

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import (
    Market,
    MarketOutcome,
)
from polybot.framework.events.resolutions import (
    LOSING_PAYOUT_PER_TOKEN,
    WINNING_PAYOUT_PER_TOKEN,
)

from .values import (
    _nested_value,
    _non_negative_decimal,
    _optional_positive_decimal,
    _required_text,
)

class MarketResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    SETTLED = "settled"


RESOLVED_MARKET_STATUSES = frozenset(MarketResolutionStatus)


def normalize_market(source: SdkMarket) -> Market:
    condition_id = _required_text(
        _nested_value(source, "condition_id"),
        MarketDataIssue.MISSING_CONDITION_ID,
        "market condition ID",
    )
    slug = _required_text(
        _nested_value(source, "slug"),
        MarketDataIssue.MISSING_MARKET_SLUG,
        "market slug",
    )
    question = _required_text(
        _nested_value(source, "question"),
        MarketDataIssue.MISSING_QUESTION,
        "market question",
    )
    first_token_id = _required_text(
        _nested_value(source, "outcomes", "yes", "token_id"),
        MarketDataIssue.MISSING_TOKEN_ID,
        "first outcome token ID",
    )
    second_token_id = _required_text(
        _nested_value(source, "outcomes", "no", "token_id"),
        MarketDataIssue.MISSING_TOKEN_ID,
        "second outcome token ID",
    )
    first_label = _required_text(
        _nested_value(source, "outcomes", "yes", "label"),
        MarketDataIssue.INVALID_MARKET_PARAMETERS,
        "first outcome label",
    )
    second_label = _required_text(
        _nested_value(source, "outcomes", "no", "label"),
        MarketDataIssue.INVALID_MARKET_PARAMETERS,
        "second outcome label",
    )
    if first_token_id == second_token_id:
        raise MarketDataError(
            MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
            "market outcomes must have distinct token IDs",
        )
    minimum_tick_size = _optional_positive_decimal(
        _nested_value(source, "trading", "minimum_tick_size"),
        "minimum tick size",
    )
    minimum_order_size = _optional_positive_decimal(
        _nested_value(source, "trading", "minimum_order_size"),
        "minimum order size",
    )
    neg_risk = _nested_value(source, "state", "neg_risk")
    if not isinstance(neg_risk, bool):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market negative-risk flag is missing",
        )

    fees_enabled = _nested_value(source, "trading", "fees_enabled")
    if not isinstance(fees_enabled, bool):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market fee-enabled flag is missing",
        )

    fee_rate = Decimal("0")
    if fees_enabled:
        fee_schedule = _nested_value(source, "trading", "fee_schedule")
        if fee_schedule is None:
            raise MarketDataError(
                MarketDataIssue.INVALID_MARKET_PARAMETERS,
                "fee-enabled market has no fee schedule",
            )
        fee_rate = _non_negative_decimal(
            _nested_value(fee_schedule, "rate"),
            "fee rate",
        )

    first_price = _nested_value(source, "outcomes", "yes", "price")
    second_price = _nested_value(source, "outcomes", "no", "price")
    resolution_status = _nested_value(source, "resolution", "uma_resolution_status")
    status_value = getattr(resolution_status, "value", resolution_status)
    normalized_status = (
        status_value.strip().casefold() if isinstance(status_value, str) else status_value
    )
    resolved = (
        normalized_status in RESOLVED_MARKET_STATUSES
        or _nested_value(source, "state", "closed") is True
    )
    winning_token_id = None
    winning_outcome = None
    if (
        resolved
        and first_price == WINNING_PAYOUT_PER_TOKEN
        and second_price == LOSING_PAYOUT_PER_TOKEN
    ):
        winning_token_id = first_token_id
        winning_outcome = first_label
    elif (
        resolved
        and second_price == WINNING_PAYOUT_PER_TOKEN
        and first_price == LOSING_PAYOUT_PER_TOKEN
    ):
        winning_token_id = second_token_id
        winning_outcome = second_label
    else:
        resolved = False

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
    )
