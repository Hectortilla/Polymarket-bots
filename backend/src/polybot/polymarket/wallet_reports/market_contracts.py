"""Normalized Gamma market payload fields."""

from typing import Final, TypedDict

from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_SLUG_FIELD,
    CONDITION_ID_FIELD,
)

MARKET_QUESTION_FIELD: Final = "question"
MARKET_START_DATE_FIELD: Final = "startDate"
MARKET_END_DATE_FIELD: Final = "endDate"
MARKET_ACTIVE_FIELD: Final = "active"
MARKET_CLOSED_FIELD: Final = "closed"
MARKET_WINNING_OUTCOME_FIELD: Final = "winningOutcome"
MARKET_OUTCOMES_FIELD: Final = "outcomes"

GammaMarketPayload = TypedDict(
    "GammaMarketPayload",
    {
        CONDITION_ID_FIELD: str,
        ACTIVITY_SLUG_FIELD: str,
        MARKET_QUESTION_FIELD: str,
        MARKET_START_DATE_FIELD: str | None,
        MARKET_END_DATE_FIELD: str | None,
        MARKET_ACTIVE_FIELD: bool | None,
        MARKET_CLOSED_FIELD: bool | None,
        MARKET_WINNING_OUTCOME_FIELD: str | None,
        MARKET_OUTCOMES_FIELD: list[str],
    },
)
