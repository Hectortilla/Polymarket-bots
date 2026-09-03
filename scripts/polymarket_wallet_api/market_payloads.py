"""Official-client Gamma models normalized into market payload fields."""

from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_SLUG_FIELD,
    CONDITION_ID_FIELD,
    SDK_CONDITION_ID_ATTRIBUTE,
    SDK_SLUG_ATTRIBUTE,
)

from .market_contracts import (
    MARKET_ACTIVE_FIELD,
    MARKET_CLOSED_FIELD,
    MARKET_END_DATE_FIELD,
    MARKET_OUTCOMES_FIELD,
    MARKET_QUESTION_FIELD,
    MARKET_START_DATE_FIELD,
    MARKET_WINNING_OUTCOME_FIELD,
    SDK_ACTIVE_ATTRIBUTE,
    SDK_CLOSED_ATTRIBUTE,
    SDK_END_DATE_ATTRIBUTE,
    SDK_MARKET_OUTCOMES_ATTRIBUTE,
    SDK_MARKET_QUESTION_ATTRIBUTE,
    SDK_MARKET_RESOLUTION_ATTRIBUTE,
    SDK_MARKET_SCHEDULE_ATTRIBUTE,
    SDK_MARKET_STATE_ATTRIBUTE,
    SDK_START_DATE_ATTRIBUTE,
    SDK_WINNING_OUTCOME_ATTRIBUTE,
)


def market_payload(market: object) -> dict[str, object]:
    state = getattr(market, SDK_MARKET_STATE_ATTRIBUTE, None)
    schedule = getattr(market, SDK_MARKET_SCHEDULE_ATTRIBUTE, None)
    resolution = getattr(market, SDK_MARKET_RESOLUTION_ATTRIBUTE, None)
    return {
        CONDITION_ID_FIELD: str(
            getattr(market, SDK_CONDITION_ID_ATTRIBUTE, "") or ""
        ),
        ACTIVITY_SLUG_FIELD: getattr(market, SDK_SLUG_ATTRIBUTE, None),
        MARKET_QUESTION_FIELD: getattr(market, SDK_MARKET_QUESTION_ATTRIBUTE, None),
        MARKET_START_DATE_FIELD: getattr(schedule, SDK_START_DATE_ATTRIBUTE, None),
        MARKET_END_DATE_FIELD: getattr(schedule, SDK_END_DATE_ATTRIBUTE, None),
        MARKET_ACTIVE_FIELD: getattr(state, SDK_ACTIVE_ATTRIBUTE, None),
        MARKET_CLOSED_FIELD: getattr(state, SDK_CLOSED_ATTRIBUTE, None),
        MARKET_WINNING_OUTCOME_FIELD: getattr(
            resolution,
            SDK_WINNING_OUTCOME_ATTRIBUTE,
            None,
        ),
        MARKET_OUTCOMES_FIELD: getattr(market, SDK_MARKET_OUTCOMES_ATTRIBUTE, None),
    }
