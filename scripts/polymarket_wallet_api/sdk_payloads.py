from __future__ import annotations

from datetime import datetime

from polybot.polymarket.wallet_activity.constants import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TITLE_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    POSITION_SIZE_FIELD,
    PROXY_WALLET_FIELD,
)
from scripts.polymarket_wallet_api.constants import (
    MARKET_ACTIVE_FIELD,
    MARKET_CLOSED_FIELD,
    MARKET_END_DATE_FIELD,
    MARKET_OUTCOMES_FIELD,
    MARKET_QUESTION_FIELD,
    MARKET_START_DATE_FIELD,
    MARKET_WINNING_OUTCOME_FIELD,
)


def activity_payload(model: object) -> dict[str, object]:
    timestamp = getattr(model, "timestamp", None)
    if isinstance(timestamp, datetime):
        timestamp = timestamp.timestamp()
    return {
        PROXY_WALLET_FIELD: str(getattr(model, "wallet", "") or ""),
        ACTIVITY_TIMESTAMP_FIELD: timestamp,
        CONDITION_ID_FIELD: str(getattr(model, "condition_id", "") or ""),
        ACTIVITY_TYPE_FIELD: str(getattr(model, "type", "")),
        ACTIVITY_SIZE_FIELD: getattr(model, "shares", None),
        ACTIVITY_USDC_SIZE_FIELD: getattr(model, "amount", None),
        ACTIVITY_TRANSACTION_HASH_FIELD: str(
            getattr(model, "transaction_hash", "") or ""
        ),
        ACTIVITY_PRICE_FIELD: getattr(model, "price", None),
        ACTIVITY_TOKEN_ID_FIELD: str(getattr(model, "token_id", "") or ""),
        ACTIVITY_SIDE_FIELD: str(getattr(model, "side", "")),
        ACTIVITY_TITLE_FIELD: getattr(model, "title", None),
        ACTIVITY_SLUG_FIELD: getattr(model, "slug", None),
        ACTIVITY_OUTCOME_FIELD: getattr(model, "outcome", None),
    }


def position_payload(model: object) -> dict[str, object]:
    return {
        PROXY_WALLET_FIELD: str(getattr(model, "wallet", "") or ""),
        CONDITION_ID_FIELD: str(getattr(model, "condition_id", "") or ""),
        POSITION_SIZE_FIELD: getattr(model, "size", None),
        POSITION_CURRENT_VALUE_FIELD: getattr(model, "current_value", None),
        POSITION_REALIZED_PNL_FIELD: getattr(model, "realized_pnl", None),
        POSITION_CASH_PNL_FIELD: getattr(model, "cash_pnl", None),
    }


def market_payload(market: object) -> dict[str, object]:
    state = getattr(market, "state", None)
    schedule = getattr(market, "schedule", None)
    resolution = getattr(market, "resolution", None)
    return {
        CONDITION_ID_FIELD: str(getattr(market, "condition_id", "") or ""),
        ACTIVITY_SLUG_FIELD: getattr(market, "slug", None),
        MARKET_QUESTION_FIELD: getattr(market, "question", None),
        MARKET_START_DATE_FIELD: getattr(schedule, "start_date", None),
        MARKET_END_DATE_FIELD: getattr(schedule, "end_date", None),
        MARKET_ACTIVE_FIELD: getattr(state, "active", None),
        MARKET_CLOSED_FIELD: getattr(state, "closed", None),
        MARKET_WINNING_OUTCOME_FIELD: getattr(resolution, "winning_outcome", None),
        MARKET_OUTCOMES_FIELD: getattr(market, "outcomes", None),
    }
