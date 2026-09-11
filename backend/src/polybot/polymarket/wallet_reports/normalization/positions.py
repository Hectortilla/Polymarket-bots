from __future__ import annotations

from collections.abc import Mapping

from polybot.polymarket.wallet_reports.contracts import (
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
    PositionRow,
)
from polybot.polymarket.wallet_reports.fields import (
    POSITION_CASH_PNL_FIELD,
    POSITION_CURRENT_VALUE_FIELD,
    POSITION_REALIZED_PNL_FIELD,
    POSITION_SIZE_FIELD,
)

from .scalars import normalized_number, normalized_wallet, required_identifier


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


def _normalize_position_row(candidate: object) -> PositionRow | None:
    if not isinstance(candidate, Mapping):
        return None
    proxy_wallet = normalized_wallet(candidate.get(PROXY_WALLET_FIELD))
    condition_id = required_identifier(candidate, CONDITION_ID_FIELD)
    if proxy_wallet is None or condition_id is None:
        return None
    size = normalized_number(candidate.get(POSITION_SIZE_FIELD))
    current_value = normalized_number(candidate.get(POSITION_CURRENT_VALUE_FIELD))
    realized_pnl = normalized_number(
        candidate.get(POSITION_REALIZED_PNL_FIELD), default=0
    )
    cash_pnl = normalized_number(candidate.get(POSITION_CASH_PNL_FIELD), default=0)
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
