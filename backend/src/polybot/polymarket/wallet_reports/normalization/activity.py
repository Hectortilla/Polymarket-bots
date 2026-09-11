from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from polybot.framework.events import Side
from polybot.framework.events.prices import is_outcome_price
from polybot.polymarket.wallet_reports.contracts import (
    ACTIVITY_OUTCOME_FIELD,
    ACTIVITY_PRICE_FIELD,
    ACTIVITY_SIDE_FIELD,
    ACTIVITY_SIZE_FIELD,
    ACTIVITY_TIMESTAMP_FIELD,
    ACTIVITY_TOKEN_ID_FIELD,
    ACTIVITY_TRANSACTION_HASH_FIELD,
    ACTIVITY_TYPE_FIELD,
    ACTIVITY_USDC_SIZE_FIELD,
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
    ActivityRow,
    ActivityType,
)

from .scalars import normalized_number, normalized_wallet, required_identifier


def normalize_activity_rows(payload: object) -> list[ActivityRow]:
    if not isinstance(payload, list):
        return []
    normalized = []
    for candidate in payload:
        row = _normalize_activity_row(candidate)
        if row is not None:
            normalized.append(row)
    return normalized


def _normalize_activity_row(candidate: object) -> ActivityRow | None:
    if not isinstance(candidate, Mapping):
        return None
    try:
        activity_type = ActivityType(candidate.get(ACTIVITY_TYPE_FIELD))
    except (TypeError, ValueError):
        return None
    proxy_wallet = normalized_wallet(candidate.get(PROXY_WALLET_FIELD))
    condition_id = required_identifier(candidate, CONDITION_ID_FIELD)
    if proxy_wallet is None or condition_id is None:
        return None
    row: ActivityRow = dict(candidate)  # type: ignore[assignment]
    row[PROXY_WALLET_FIELD] = proxy_wallet
    row[CONDITION_ID_FIELD] = condition_id
    row[ACTIVITY_TYPE_FIELD] = activity_type
    raw_outcome = candidate.get(ACTIVITY_OUTCOME_FIELD)
    outcome = required_identifier(candidate, ACTIVITY_OUTCOME_FIELD)
    if raw_outcome is not None and outcome is None:
        return None
    if outcome is not None:
        row[ACTIVITY_OUTCOME_FIELD] = outcome
    if activity_type is ActivityType.TRADE:
        transaction_hash = required_identifier(
            candidate, ACTIVITY_TRANSACTION_HASH_FIELD
        )
        token_id = required_identifier(candidate, ACTIVITY_TOKEN_ID_FIELD)
        if transaction_hash is None or token_id is None:
            return None
        row[ACTIVITY_TRANSACTION_HASH_FIELD] = transaction_hash
        row[ACTIVITY_TOKEN_ID_FIELD] = token_id
        try:
            row[ACTIVITY_SIDE_FIELD] = Side(candidate.get(ACTIVITY_SIDE_FIELD))
        except (TypeError, ValueError):
            return None
        size = normalized_number(candidate.get(ACTIVITY_SIZE_FIELD))
        price = normalized_number(candidate.get(ACTIVITY_PRICE_FIELD))
        usdc_size = normalized_number(candidate.get(ACTIVITY_USDC_SIZE_FIELD))
        if (
            size is None
            or price is None
            or usdc_size is None
            or size <= 0
            or not _is_outcome_price(price)
            or usdc_size < 0
        ):
            return None
        row[ACTIVITY_SIZE_FIELD] = size
        row[ACTIVITY_PRICE_FIELD] = price
        row[ACTIVITY_USDC_SIZE_FIELD] = usdc_size
    else:
        usdc_size = normalized_number(
            candidate.get(ACTIVITY_USDC_SIZE_FIELD), default=0
        )
        size = normalized_number(candidate.get(ACTIVITY_SIZE_FIELD), default=0)
        if usdc_size is None or size is None or usdc_size < 0 or size < 0:
            return None
        row[ACTIVITY_USDC_SIZE_FIELD] = usdc_size
        row[ACTIVITY_SIZE_FIELD] = size
    activity_timestamp_seconds = normalized_number(
        candidate.get(ACTIVITY_TIMESTAMP_FIELD)
    )
    if (
        activity_timestamp_seconds is None
        or activity_timestamp_seconds < 0
        or not activity_timestamp_seconds.is_integer()
    ):
        return None
    row[ACTIVITY_TIMESTAMP_FIELD] = int(activity_timestamp_seconds)
    return row


def _is_outcome_price(value: float) -> bool:
    try:
        return is_outcome_price(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return False
