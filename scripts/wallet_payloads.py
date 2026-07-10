from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from math import isfinite
from typing import Final, TypedDict

from bots.framework.events import Side

CONDITION_ID_FIELD: Final = "conditionId"
PROXY_WALLET_FIELD: Final = "proxyWallet"
ACTIVITY_TYPE_FIELD: Final = "type"
ACTIVITY_SIDE_FIELD: Final = "side"
ACTIVITY_SIZE_FIELD: Final = "size"
ACTIVITY_PRICE_FIELD: Final = "price"
ACTIVITY_USDC_SIZE_FIELD: Final = "usdcSize"
ACTIVITY_TIMESTAMP_FIELD: Final = "timestamp"
ACTIVITY_SLUG_FIELD: Final = "slug"
ACTIVITY_TITLE_FIELD: Final = "title"
ACTIVITY_OUTCOME_FIELD: Final = "outcome"
POSITION_SIZE_FIELD: Final = "size"
POSITION_CURRENT_VALUE_FIELD: Final = "currentValue"
POSITION_REALIZED_PNL_FIELD: Final = "realizedPnl"
POSITION_CASH_PNL_FIELD: Final = "cashPnl"


class ActivityRow(TypedDict, total=False):
    proxyWallet: str
    conditionId: str
    type: ActivityType
    side: Side
    size: float
    price: float
    usdcSize: float
    timestamp: int
    slug: str
    market_slug: str
    title: str
    outcome: str
    transactionHash: str
    asset: str


class PositionRow(TypedDict, total=False):
    proxyWallet: str
    conditionId: str
    size: float
    currentValue: float
    realizedPnl: float
    cashPnl: float


class ActivityType(StrEnum):
    TRADE = "TRADE"
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    REDEEM = "REDEEM"
    REWARD = "REWARD"


def normalize_gamma_market(payload: object) -> dict[str, object] | None:
    if isinstance(payload, list):
        candidate = payload[0] if payload else None
    elif isinstance(payload, Mapping):
        markets = payload.get("markets")
        candidate = markets[0] if isinstance(markets, list) and markets else payload
    else:
        return None
    return dict(candidate) if isinstance(candidate, Mapping) else None


def normalize_gamma_event(payload: object) -> dict[str, object] | None:
    candidate = payload[0] if isinstance(payload, list) and payload else payload
    return dict(candidate) if isinstance(candidate, Mapping) else None


def normalize_activity_rows(payload: object) -> list[ActivityRow]:
    if not isinstance(payload, list):
        return []
    normalized = []
    for candidate in payload:
        row = _normalize_activity_row(candidate)
        if row is not None:
            normalized.append(row)
    return normalized


def normalize_position_rows(payload: object) -> list[PositionRow]:
    if not isinstance(payload, list):
        return []
    normalized = []
    for candidate in payload:
        row = _normalize_position_row(candidate)
        if row is not None:
            normalized.append(row)
    return normalized


def normalize_market_position_rows(payload: object) -> list[PositionRow]:
    if not isinstance(payload, list) or not payload:
        return []
    envelope = payload[0]
    if not isinstance(envelope, Mapping):
        return []
    return normalize_position_rows(envelope.get("positions"))


def _normalize_activity_row(candidate: object) -> ActivityRow | None:
    if not isinstance(candidate, Mapping):
        return None
    try:
        activity_type = ActivityType(candidate.get(ACTIVITY_TYPE_FIELD))
    except (TypeError, ValueError):
        return None
    row: ActivityRow = dict(candidate)  # type: ignore[assignment]
    row[ACTIVITY_TYPE_FIELD] = activity_type
    if activity_type is ActivityType.TRADE:
        try:
            row[ACTIVITY_SIDE_FIELD] = Side(candidate.get(ACTIVITY_SIDE_FIELD))
        except (TypeError, ValueError):
            return None
        size = _normalized_number(candidate.get(ACTIVITY_SIZE_FIELD))
        price = _normalized_number(candidate.get(ACTIVITY_PRICE_FIELD))
        usdc_size = _normalized_number(candidate.get(ACTIVITY_USDC_SIZE_FIELD))
        if (
            size is None
            or price is None
            or usdc_size is None
            or size <= 0
            or not 0 < price <= 1
            or usdc_size < 0
        ):
            return None
        row[ACTIVITY_SIZE_FIELD] = size
        row[ACTIVITY_PRICE_FIELD] = price
        row[ACTIVITY_USDC_SIZE_FIELD] = usdc_size
    else:
        usdc_size = _normalized_number(candidate.get(ACTIVITY_USDC_SIZE_FIELD), default=0)
        size = _normalized_number(candidate.get(ACTIVITY_SIZE_FIELD), default=0)
        if usdc_size is None or size is None or usdc_size < 0 or size < 0:
            return None
        row[ACTIVITY_USDC_SIZE_FIELD] = usdc_size
        row[ACTIVITY_SIZE_FIELD] = size
    timestamp = _normalized_number(candidate.get(ACTIVITY_TIMESTAMP_FIELD))
    if timestamp is None or timestamp < 0 or not timestamp.is_integer():
        return None
    row[ACTIVITY_TIMESTAMP_FIELD] = int(timestamp)
    return row


def _normalize_position_row(candidate: object) -> PositionRow | None:
    if not isinstance(candidate, Mapping):
        return None
    size = _normalized_number(candidate.get(POSITION_SIZE_FIELD))
    current_value = _normalized_number(candidate.get(POSITION_CURRENT_VALUE_FIELD))
    realized_pnl = _normalized_number(candidate.get(POSITION_REALIZED_PNL_FIELD), default=0)
    cash_pnl = _normalized_number(candidate.get(POSITION_CASH_PNL_FIELD), default=0)
    if (
        size is None
        or current_value is None
        or realized_pnl is None
        or cash_pnl is None
        or size < 0
        or current_value < 0
    ):
        return None
    row: PositionRow = dict(candidate)  # type: ignore[assignment]
    row[POSITION_SIZE_FIELD] = size
    row[POSITION_CURRENT_VALUE_FIELD] = current_value
    row[POSITION_REALIZED_PNL_FIELD] = realized_pnl
    row[POSITION_CASH_PNL_FIELD] = cash_pnl
    return row


def _normalized_number(value: object, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return None
    try:
        normalized = float(value)
        return normalized if isfinite(normalized) else None
    except (TypeError, ValueError, OverflowError):
        return None
