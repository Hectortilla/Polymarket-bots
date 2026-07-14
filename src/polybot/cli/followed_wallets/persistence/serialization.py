"""Serialization and restoration of followed-wallet state."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from polybot.framework.events import Side
from polybot.framework.wallets import normalize_wallet_address

from ..contracts import WalletFollowState
from ..position_contracts import FollowBaseline, FollowMovement
from .schema import (
    FOLLOW_ACTIVE_FIELD,
    FOLLOW_BASELINES_FIELD,
    FOLLOW_BASIS_PRICE_FIELD,
    FOLLOW_BOOTSTRAPPED_FIELD,
    FOLLOW_CHECKPOINT_FIELD,
    FOLLOW_CONDITION_ID_FIELD,
    FOLLOW_EPOCH_FIELD,
    FOLLOW_EPOCH_HISTORY_FIELD,
    FOLLOW_MARKET_SLUG_FIELD,
    FOLLOW_MOVEMENTS_FIELD,
    FOLLOW_OUTCOME_FIELD,
    FOLLOW_PRICE_FIELD,
    FOLLOW_SETTLEMENTS_FIELD,
    FOLLOW_SIDE_FIELD,
    FOLLOW_SIZE_FIELD,
    FOLLOW_SOURCE_IDS_FIELD,
    FOLLOW_SOURCE_KEY_FIELD,
    FOLLOW_STATE_VERSION_FIELD,
    FOLLOW_TOKEN_ID_FIELD,
    FOLLOW_TRADE_TIMESTAMP_MS_FIELD,
    FOLLOW_WALLETS_FIELD,
    FOLLOWED_AT_MS_FIELD,
)
from .validation import validate_state_payload

FOLLOW_STATE_VERSION = 1


def state_from_payload(wallet: str, payload: dict[str, Any]) -> WalletFollowState:
    payload = validate_state_payload(wallet, payload, allow_missing_epoch_history=True)
    baselines = {
        baseline_payload[FOLLOW_TOKEN_ID_FIELD]: FollowBaseline(
            condition_id=baseline_payload[FOLLOW_CONDITION_ID_FIELD],
            token_id=baseline_payload[FOLLOW_TOKEN_ID_FIELD],
            market_slug=baseline_payload[FOLLOW_MARKET_SLUG_FIELD],
            size=Decimal(baseline_payload[FOLLOW_SIZE_FIELD]),
            basis_price=(
                None
                if baseline_payload[FOLLOW_BASIS_PRICE_FIELD] is None
                else Decimal(baseline_payload[FOLLOW_BASIS_PRICE_FIELD])
            ),
            outcome=baseline_payload.get(FOLLOW_OUTCOME_FIELD),
        )
        for baseline_payload in payload[FOLLOW_BASELINES_FIELD]
    }
    movements = {
        movement_payload[FOLLOW_SOURCE_KEY_FIELD]: FollowMovement(
            condition_id=movement_payload[FOLLOW_CONDITION_ID_FIELD],
            token_id=movement_payload[FOLLOW_TOKEN_ID_FIELD],
            side=Side(movement_payload[FOLLOW_SIDE_FIELD]),
            size=Decimal(movement_payload[FOLLOW_SIZE_FIELD]),
            price=Decimal(movement_payload[FOLLOW_PRICE_FIELD]),
            trade_timestamp_ms=movement_payload[FOLLOW_TRADE_TIMESTAMP_MS_FIELD],
            source_key=movement_payload[FOLLOW_SOURCE_KEY_FIELD],
            market_slug=movement_payload.get(FOLLOW_MARKET_SLUG_FIELD),
        )
        for movement_payload in payload[FOLLOW_MOVEMENTS_FIELD]
    }
    checkpoint = payload[FOLLOW_CHECKPOINT_FIELD]
    return WalletFollowState(
        wallet=wallet,
        epoch=payload[FOLLOW_EPOCH_FIELD],
        active=payload[FOLLOW_ACTIVE_FIELD],
        followed_at_ms=payload[FOLLOWED_AT_MS_FIELD],
        bootstrapped=payload[FOLLOW_BOOTSTRAPPED_FIELD],
        baselines=baselines,
        movements=movements,
        source_ids=set(payload[FOLLOW_SOURCE_IDS_FIELD]),
        checkpoint=None if checkpoint is None else (checkpoint[0], checkpoint[1]),
        settlements=list(payload[FOLLOW_SETTLEMENTS_FIELD]),
        epoch_history=list(payload[FOLLOW_EPOCH_HISTORY_FIELD]),
    )


def load_states(payload: dict[str, Any]) -> dict[str, WalletFollowState]:
    if not payload:
        return {}
    if payload.get(
        FOLLOW_STATE_VERSION_FIELD
    ) != FOLLOW_STATE_VERSION or not isinstance(
        payload.get(FOLLOW_WALLETS_FIELD), dict
    ):
        raise ValueError("unsupported followed-wallet state format")
    states: dict[str, WalletFollowState] = {}
    for wallet, state_payload_value in payload[FOLLOW_WALLETS_FIELD].items():
        if not isinstance(wallet, str) or not wallet.strip():
            raise ValueError("followed-wallet state contains an invalid wallet key")
        if not isinstance(state_payload_value, dict):
            raise ValueError("followed-wallet state record must be an object")
        if FOLLOW_EPOCH_HISTORY_FIELD not in state_payload_value:
            raise ValueError("followed-wallet state is missing epoch history")
        normalized_wallet = normalize_wallet_address(wallet.strip())
        if normalized_wallet in states:
            raise ValueError("followed-wallet state contains duplicate wallet keys")
        states[normalized_wallet] = state_from_payload(
            normalized_wallet, state_payload_value
        )
    return states


def root_payload(wallets: dict[str, WalletFollowState]) -> dict[str, Any]:
    return {
        FOLLOW_STATE_VERSION_FIELD: FOLLOW_STATE_VERSION,
        FOLLOW_WALLETS_FIELD: {
            wallet: state.to_payload() for wallet, state in sorted(wallets.items())
        },
    }
