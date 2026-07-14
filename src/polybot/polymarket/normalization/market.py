from __future__ import annotations

from decimal import Decimal

from polymarket.models.gamma.market import Market as SdkMarket

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.types import (
    Market,
    MarketOutcome,
)
from polybot.framework.events.resolutions import (
    LOSING_PAYOUT_PER_TOKEN,
    NO_OUTCOME,
    WINNING_PAYOUT_PER_TOKEN,
    YES_OUTCOME,
)

from .values import (
    _nested_value,
    _non_negative_decimal,
    _optional_positive_decimal,
    _required_text,
)

RESOLVED_MARKET_STATUSES = frozenset({"resolved", "settled"})
WINNING_PAYOUT = WINNING_PAYOUT_PER_TOKEN
LOSING_PAYOUT = LOSING_PAYOUT_PER_TOKEN


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
    yes_token_id = _required_text(
        _nested_value(source, "outcomes", "yes", "token_id"),
        MarketDataIssue.MISSING_TOKEN_ID,
        "YES token ID",
    )
    no_token_id = _required_text(
        _nested_value(source, "outcomes", "no", "token_id"),
        MarketDataIssue.MISSING_TOKEN_ID,
        "NO token ID",
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

    yes_price = _nested_value(source, "outcomes", "yes", "price")
    no_price = _nested_value(source, "outcomes", "no", "price")
    resolution_status = _nested_value(source, "resolution", "uma_resolution_status")
    status_value = getattr(resolution_status, "value", resolution_status)
    resolved = (
        status_value in RESOLVED_MARKET_STATUSES
        or _nested_value(source, "state", "closed") is True
    )
    winning_token_id = None
    winning_outcome = None
    if resolved and yes_price == WINNING_PAYOUT and no_price == LOSING_PAYOUT:
        winning_token_id = yes_token_id
        winning_outcome = YES_OUTCOME
    elif resolved and no_price == WINNING_PAYOUT and yes_price == LOSING_PAYOUT:
        winning_token_id = no_token_id
        winning_outcome = NO_OUTCOME
    else:
        resolved = False

    return Market(
        condition_id=condition_id,
        slug=slug,
        question=question,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        minimum_tick_size=minimum_tick_size,
        minimum_order_size=minimum_order_size,
        neg_risk=neg_risk,
        fee_rate=fee_rate,
        outcomes=(
            MarketOutcome(YES_OUTCOME, yes_token_id),
            MarketOutcome(NO_OUTCOME, no_token_id),
        ),
        resolved=resolved,
        winning_token_id=winning_token_id,
        winning_outcome=winning_outcome,
    )
