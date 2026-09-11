"""Convert official Gamma models into the report's JSON-safe market contract."""

from datetime import datetime

from polybot.polymarket.normalization.market import normalize_market
from polybot.polymarket.normalization.timestamps import datetime_to_epoch_ms
from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_SLUG_FIELD,
    CONDITION_ID_FIELD,
)

from polymarket.models.gamma.market import Market as SdkMarket

from .market_contracts import (
    MARKET_ACTIVE_FIELD,
    MARKET_CLOSED_FIELD,
    MARKET_END_DATE_FIELD,
    MARKET_OUTCOMES_FIELD,
    MARKET_QUESTION_FIELD,
    MARKET_START_DATE_FIELD,
    MARKET_WINNING_OUTCOME_FIELD,
    GammaMarketPayload,
)


def market_payload(source: SdkMarket) -> GammaMarketPayload:
    market = normalize_market(source)
    return {
        CONDITION_ID_FIELD: market.condition_id,
        ACTIVITY_SLUG_FIELD: market.slug,
        MARKET_QUESTION_FIELD: market.question,
        MARKET_START_DATE_FIELD: _date_text(getattr(source.state, "start_date", None)),
        MARKET_END_DATE_FIELD: _date_text(getattr(source.state, "end_date", None)),
        MARKET_ACTIVE_FIELD: market.active,
        MARKET_CLOSED_FIELD: market.closed,
        MARKET_WINNING_OUTCOME_FIELD: market.winning_outcome,
        MARKET_OUTCOMES_FIELD: [outcome.label for outcome in market.outcomes],
    }


def _date_text(value: datetime | None) -> str | None:
    datetime_to_epoch_ms(value)
    return None if value is None else value.isoformat()
