"""Validation of persisted followed-wallet payloads."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from collections.abc import Iterable
from typing import Any

from polybot.framework.events import Side
from polybot.framework.events.prices import OUTCOME_PRICE_CEILING
from polybot.framework.events.wallet_trades import source_key_belongs_to_wallet
from polybot.framework.events.resolutions import (
    RESOLUTION_RESOLVED_AT_MS_FIELD,
    RESOLUTION_WINNING_TOKEN_ID_FIELD,
    SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD,
    SETTLED_POSITION_OWNER_FIELD,
    SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD,
    SETTLED_POSITION_REALIZED_PNL_USDC_FIELD,
    SETTLED_POSITION_SIZE_FIELD,
    SETTLED_POSITION_TOKEN_ID_FIELD,
)
from polybot.framework.wallets import normalize_wallet_address

from .schema import (
    FOLLOW_ACTIVE_FIELD,
    FOLLOW_BASELINES_FIELD,
    FOLLOW_BASIS_PRICE_FIELD,
    FOLLOW_BOOTSTRAPPED_FIELD,
    FOLLOW_CHECKPOINT_FIELD,
    FOLLOW_CONDITION_ID_FIELD,
    FOLLOW_EPOCH_FIELD,
    FOLLOW_EPOCH_HISTORY_FIELD,
    FOLLOW_GROSS_REALIZED_PNL_FIELD,
    FOLLOW_MARKET_SLUG_FIELD,
    FOLLOW_MOVEMENTS_FIELD,
    FOLLOW_OUTCOME_FIELD,
    FOLLOW_POSITIONS_FIELD,
    FOLLOW_PRICE_FIELD,
    FOLLOW_SETTLEMENTS_FIELD,
    FOLLOW_SIDE_FIELD,
    FOLLOW_SIZE_FIELD,
    FOLLOW_SOURCE_IDS_FIELD,
    FOLLOW_SOURCE_KEY_FIELD,
    FOLLOW_TOKEN_ID_FIELD,
    FOLLOW_TRADE_TIMESTAMP_MS_FIELD,
    FOLLOWED_AT_MS_FIELD,
)


def validate_state_payload(
    wallet: str,
    payload: dict[str, Any],
    *,
    allow_missing_epoch_history: bool = False,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"followed-wallet state for {wallet} must be an object")
    _require_int(payload, FOLLOW_EPOCH_FIELD, minimum=1)
    _require_bool(payload, FOLLOW_ACTIVE_FIELD)
    _require_int(payload, FOLLOWED_AT_MS_FIELD, minimum=0)
    _require_bool(payload, FOLLOW_BOOTSTRAPPED_FIELD)
    baselines = _require_list(payload, FOLLOW_BASELINES_FIELD)
    movements = _require_list(payload, FOLLOW_MOVEMENTS_FIELD)
    source_ids = _require_string_list(payload, FOLLOW_SOURCE_IDS_FIELD)
    checkpoint = _require_key(payload, FOLLOW_CHECKPOINT_FIELD)
    if checkpoint is not None:
        if (
            not isinstance(checkpoint, list)
            or len(checkpoint) != 2
            or not isinstance(checkpoint[0], int)
            or isinstance(checkpoint[0], bool)
            or checkpoint[0] < 0
            or not isinstance(checkpoint[1], str)
            or not checkpoint[1]
        ):
            raise ValueError("followed-wallet checkpoint is invalid")
        _require_owned_source_key(wallet, checkpoint[1], "checkpoint")
    settlements = _require_record_list(payload, FOLLOW_SETTLEMENTS_FIELD)
    if FOLLOW_EPOCH_HISTORY_FIELD not in payload and not allow_missing_epoch_history:
        raise ValueError("followed-wallet state is missing epoch history")
    epoch_history = (
        []
        if FOLLOW_EPOCH_HISTORY_FIELD not in payload
        else _require_record_list(payload, FOLLOW_EPOCH_HISTORY_FIELD)
    )
    for baseline_payload in baselines:
        _validate_baseline(baseline_payload)
    for movement_payload in movements:
        _validate_movement(wallet, movement_payload)
    for settlement_payload in settlements:
        _validate_settlement(wallet, settlement_payload)
    for historical_payload in epoch_history:
        validate_state_payload(
            wallet, historical_payload, allow_missing_epoch_history=True
        )
    _reject_duplicates(
        (baseline[FOLLOW_TOKEN_ID_FIELD] for baseline in baselines),
        "baseline token IDs",
    )
    _reject_duplicates(
        (movement[FOLLOW_SOURCE_KEY_FIELD] for movement in movements),
        "movement source keys",
    )
    _reject_duplicates(source_ids, "source IDs")
    for source_key in source_ids:
        _require_owned_source_key(wallet, source_key, "source ID")
    _reject_duplicates(
        (settlement[FOLLOW_CONDITION_ID_FIELD] for settlement in settlements),
        "settlement condition IDs",
    )
    _reject_duplicates(
        (historical[FOLLOW_EPOCH_FIELD] for historical in epoch_history),
        "history epochs",
    )
    return {
        **payload,
        FOLLOW_BASELINES_FIELD: baselines,
        FOLLOW_MOVEMENTS_FIELD: movements,
        FOLLOW_SOURCE_IDS_FIELD: source_ids,
        FOLLOW_SETTLEMENTS_FIELD: settlements,
        FOLLOW_EPOCH_HISTORY_FIELD: epoch_history,
    }


def _validate_baseline(payload: dict[str, Any]) -> None:
    _require_text(payload, FOLLOW_CONDITION_ID_FIELD)
    _require_text(payload, FOLLOW_TOKEN_ID_FIELD)
    _require_text(payload, FOLLOW_MARKET_SLUG_FIELD)
    _require_decimal(payload, FOLLOW_SIZE_FIELD, positive=True)
    basis_price = _require_key(payload, FOLLOW_BASIS_PRICE_FIELD)
    if basis_price is not None:
        _decimal_value(
            basis_price,
            FOLLOW_BASIS_PRICE_FIELD,
            non_negative=True,
            maximum=OUTCOME_PRICE_CEILING,
        )
    outcome = payload.get(FOLLOW_OUTCOME_FIELD)
    if outcome is not None and (not isinstance(outcome, str) or not outcome.strip()):
        raise ValueError("followed-wallet baseline outcome is invalid")


def _validate_movement(wallet: str, payload: dict[str, Any]) -> None:
    _require_text(payload, FOLLOW_CONDITION_ID_FIELD)
    _require_text(payload, FOLLOW_TOKEN_ID_FIELD)
    if payload.get(FOLLOW_SIDE_FIELD) not in {Side.BUY.value, Side.SELL.value}:
        raise ValueError("followed-wallet movement side is invalid")
    _require_decimal(payload, FOLLOW_SIZE_FIELD, positive=True)
    _decimal_value(
        payload.get(FOLLOW_PRICE_FIELD),
        FOLLOW_PRICE_FIELD,
        positive=True,
        maximum=OUTCOME_PRICE_CEILING,
    )
    _require_int(payload, FOLLOW_TRADE_TIMESTAMP_MS_FIELD, minimum=0)
    source_key = _require_text(payload, FOLLOW_SOURCE_KEY_FIELD)
    _require_owned_source_key(wallet, source_key, "movement source key")
    market_slug = payload.get(FOLLOW_MARKET_SLUG_FIELD)
    if market_slug is not None and (
        not isinstance(market_slug, str) or not market_slug
    ):
        raise ValueError("followed-wallet movement market slug is invalid")


def _validate_settlement(wallet: str, payload: dict[str, Any]) -> None:
    _require_text(payload, FOLLOW_CONDITION_ID_FIELD)
    _require_text(payload, RESOLUTION_WINNING_TOKEN_ID_FIELD)
    _require_int(payload, RESOLUTION_RESOLVED_AT_MS_FIELD, minimum=0)
    positions = payload.get(FOLLOW_POSITIONS_FIELD)
    if not isinstance(positions, list) or not all(
        isinstance(position, dict) for position in positions
    ):
        raise ValueError("followed-wallet settlement positions must be a list")
    for position in positions:
        owner = _require_text(position, SETTLED_POSITION_OWNER_FIELD)
        if normalize_wallet_address(owner) != normalize_wallet_address(wallet):
            raise ValueError("followed-wallet settlement position owner is invalid")
        _require_text(position, SETTLED_POSITION_TOKEN_ID_FIELD)
        _require_decimal(position, SETTLED_POSITION_SIZE_FIELD)
        _decimal_value(
            position.get(SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD),
            SETTLED_POSITION_PAYOUT_PER_TOKEN_FIELD,
            non_negative=True,
            maximum=OUTCOME_PRICE_CEILING,
        )
        _decimal_value(
            position.get(SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD),
            SETTLED_POSITION_CASH_PAYOUT_USDC_FIELD,
        )
        realized = _require_key(position, SETTLED_POSITION_REALIZED_PNL_USDC_FIELD)
        if realized is not None:
            _decimal_value(realized, SETTLED_POSITION_REALIZED_PNL_USDC_FIELD)
    gross = _require_key(payload, FOLLOW_GROSS_REALIZED_PNL_FIELD)
    if gross is not None:
        _decimal_value(gross, FOLLOW_GROSS_REALIZED_PNL_FIELD)
    baselines = _require_record_list(payload, FOLLOW_BASELINES_FIELD)
    movements = _require_record_list(payload, FOLLOW_MOVEMENTS_FIELD)
    for baseline in baselines:
        _validate_baseline(baseline)
    for movement in movements:
        _validate_movement(wallet, movement)
    _reject_duplicates(
        (position[SETTLED_POSITION_TOKEN_ID_FIELD] for position in positions),
        "settlement position token IDs",
    )
    _reject_duplicates(
        (baseline[FOLLOW_TOKEN_ID_FIELD] for baseline in baselines),
        "settlement baseline token IDs",
    )
    _reject_duplicates(
        (movement[FOLLOW_SOURCE_KEY_FIELD] for movement in movements),
        "settlement movement source keys",
    )


def _reject_duplicates(values: Iterable[object], label: str) -> None:
    sequence = tuple(values)
    if len(sequence) != len(set(sequence)):
        raise ValueError(f"followed-wallet {label} contain duplicates")


def _require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"followed-wallet {key} must be a list")
    return value


def _require_key(payload: dict[str, Any], key: str) -> object:
    if key not in payload:
        raise ValueError(f"followed-wallet {key} is missing")
    return payload[key]


def _require_record_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = _require_list(payload, key)
    if not all(isinstance(value, dict) for value in values):
        raise ValueError(f"followed-wallet {key} must contain objects")
    return values


def _require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    values = _require_list(payload, key)
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError(f"followed-wallet {key} must contain non-empty strings")
    return values


def _require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"followed-wallet {key} is invalid")
    return value


def _require_owned_source_key(wallet: str, source_key: str, label: str) -> None:
    if not source_key_belongs_to_wallet(wallet, source_key):
        raise ValueError(f"followed-wallet {label} does not belong to {wallet}")


def _require_int(payload: dict[str, Any], key: str, *, minimum: int) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"followed-wallet {key} is invalid")
    return value


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"followed-wallet {key} is invalid")
    return value


def _require_decimal(
    payload: dict[str, Any], key: str, *, positive: bool = False
) -> Decimal:
    return _decimal_value(payload.get(key), key, positive=positive)


def _decimal_value(
    value: object,
    key: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
    maximum: Decimal | None = None,
) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"followed-wallet {key} is invalid")
    try:
        decimal = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"followed-wallet {key} is invalid") from error
    if (
        not decimal.is_finite()
        or (positive and decimal <= 0)
        or (non_negative and decimal < 0)
        or (maximum is not None and decimal > maximum)
    ):
        raise ValueError(f"followed-wallet {key} is invalid")
    return decimal
