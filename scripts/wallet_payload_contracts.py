"""Dependency-light contracts for normalized wallet-analysis payloads."""

from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from polybot.polymarket.wallet_activity.fields import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TITLE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    ENRICHED_MARKET_SLUG_FIELD,
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    POSITION_SIZE_FIELD,
    PROXY_WALLET_FIELD,
    TRADE_ACTIVITY_TYPE,
)


class ActivityType(StrEnum):
    TRADE = TRADE_ACTIVITY_TYPE
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    REDEEM = "REDEEM"
    REWARD = "REWARD"


ActivityRow = TypedDict(
    "ActivityRow",
    {
        PROXY_WALLET_FIELD: str,
        CONDITION_ID_FIELD: str,
        ACTIVITY_TYPE_FIELD: ActivityType,
        ACTIVITY_SIDE_FIELD: str,
        ACTIVITY_SIZE_FIELD: float,
        ACTIVITY_PRICE_FIELD: float,
        ACTIVITY_USDC_SIZE_FIELD: float,
        ACTIVITY_TIMESTAMP_FIELD: int,
        ACTIVITY_SLUG_FIELD: str,
        ENRICHED_MARKET_SLUG_FIELD: str,
        ACTIVITY_TITLE_FIELD: str,
        ACTIVITY_OUTCOME_FIELD: str,
        ACTIVITY_TRANSACTION_HASH_FIELD: str,
        ACTIVITY_TOKEN_ID_FIELD: str,
    },
    total=False,
)

PositionRow = TypedDict(
    "PositionRow",
    {
        PROXY_WALLET_FIELD: str,
        CONDITION_ID_FIELD: str,
        POSITION_SIZE_FIELD: float,
        POSITION_CURRENT_VALUE_FIELD: float,
        POSITION_REALIZED_PNL_FIELD: float,
        POSITION_CASH_PNL_FIELD: float,
    },
    total=False,
)
