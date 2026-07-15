from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite

from polybot.framework.events import Side

from scripts.wallet_payload_contracts import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SLUG_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TITLE_FIELD,
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
    ActivityRow,
    ActivityType,
    PositionRow,
)


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
    proxy_wallet = _required_identifier(candidate, PROXY_WALLET_FIELD)
    condition_id = _required_identifier(candidate, CONDITION_ID_FIELD)
    if proxy_wallet is None or condition_id is None:
        return None
    row: ActivityRow = dict(candidate)  # type: ignore[assignment]
    row[PROXY_WALLET_FIELD] = proxy_wallet
    row[CONDITION_ID_FIELD] = condition_id
    row[ACTIVITY_TYPE_FIELD] = activity_type
    raw_outcome = candidate.get(ACTIVITY_OUTCOME_FIELD)
    outcome = _required_identifier(candidate, ACTIVITY_OUTCOME_FIELD)
    if raw_outcome is not None and outcome is None:
        return None
    if outcome is not None:
        row[ACTIVITY_OUTCOME_FIELD] = outcome
    if activity_type is ActivityType.TRADE:
        transaction_hash = _required_identifier(
            candidate, ACTIVITY_TRANSACTION_HASH_FIELD
        )
        token_id = _required_identifier(candidate, ACTIVITY_TOKEN_ID_FIELD)
        if transaction_hash is None or token_id is None:
            return None
        row[ACTIVITY_TRANSACTION_HASH_FIELD] = transaction_hash
        row[ACTIVITY_TOKEN_ID_FIELD] = token_id
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
        usdc_size = _normalized_number(
            candidate.get(ACTIVITY_USDC_SIZE_FIELD), default=0
        )
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
    proxy_wallet = _required_identifier(candidate, PROXY_WALLET_FIELD)
    condition_id = _required_identifier(candidate, CONDITION_ID_FIELD)
    if proxy_wallet is None or condition_id is None:
        return None
    size = _normalized_number(candidate.get(POSITION_SIZE_FIELD))
    current_value = _normalized_number(candidate.get(POSITION_CURRENT_VALUE_FIELD))
    realized_pnl = _normalized_number(
        candidate.get(POSITION_REALIZED_PNL_FIELD), default=0
    )
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
    row[PROXY_WALLET_FIELD] = proxy_wallet
    row[CONDITION_ID_FIELD] = condition_id
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


def _required_identifier(candidate: Mapping[object, object], field: str) -> str | None:
    value = candidate.get(field)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
