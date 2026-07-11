from __future__ import annotations

from datetime import datetime

from scripts.wallet_payloads import CONDITION_ID_FIELD, PROXY_WALLET_FIELD


def activity_payload(model: object) -> dict[str, object]:
    timestamp = getattr(model, "timestamp", None)
    if isinstance(timestamp, datetime):
        timestamp = timestamp.timestamp()
    return {
        PROXY_WALLET_FIELD: str(getattr(model, "wallet", "") or ""),
        "timestamp": timestamp,
        CONDITION_ID_FIELD: str(getattr(model, "condition_id", "") or ""),
        "type": str(getattr(model, "type", "")),
        "size": getattr(model, "shares", None),
        "usdcSize": getattr(model, "amount", None),
        "transactionHash": str(getattr(model, "transaction_hash", "") or ""),
        "price": getattr(model, "price", None),
        "asset": str(getattr(model, "token_id", "") or ""),
        "side": str(getattr(model, "side", "")),
        "title": getattr(model, "title", None),
        "slug": getattr(model, "slug", None),
        "outcome": getattr(model, "outcome", None),
    }


def position_payload(model: object) -> dict[str, object]:
    return {
        PROXY_WALLET_FIELD: str(getattr(model, "wallet", "") or ""),
        CONDITION_ID_FIELD: str(getattr(model, "condition_id", "") or ""),
        "size": getattr(model, "size", None),
        "currentValue": getattr(model, "current_value", None),
        "realizedPnl": getattr(model, "realized_pnl", None),
        "cashPnl": getattr(model, "cash_pnl", None),
    }


def market_payload(market: object) -> dict[str, object]:
    state = getattr(market, "state", None)
    schedule = getattr(market, "schedule", None)
    resolution = getattr(market, "resolution", None)
    return {
        CONDITION_ID_FIELD: str(getattr(market, "condition_id", "") or ""),
        "slug": getattr(market, "slug", None),
        "question": getattr(market, "question", None),
        "startDate": getattr(schedule, "start_date", None),
        "endDate": getattr(schedule, "end_date", None),
        "active": getattr(state, "active", None),
        "closed": getattr(state, "closed", None),
        "winningOutcome": getattr(resolution, "winning_outcome", None),
        "outcomes": getattr(market, "outcomes", None),
    }
