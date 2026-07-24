"""Serialization and restoration of followed-wallet state."""

from __future__ import annotations

from typing import Any

from polybot.framework.wallets import validate_wallet_address

from ..contracts import WalletFollowState
from .schema import (
    FOLLOW_EPOCH_HISTORY_FIELD,
    FOLLOW_STATE_VERSION_FIELD,
    FOLLOW_WALLETS_FIELD,
)

FOLLOW_STATE_VERSION = 1


def load_states(payload: dict[str, Any]) -> dict[str, WalletFollowState]:
    if not payload:
        return {}
    version = payload.get(FOLLOW_STATE_VERSION_FIELD)
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != FOLLOW_STATE_VERSION
        or not isinstance(
            payload.get(FOLLOW_WALLETS_FIELD), dict
        )
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
        normalized_wallet = validate_wallet_address(wallet)
        if normalized_wallet in states:
            raise ValueError("followed-wallet state contains duplicate wallet keys")
        states[normalized_wallet] = WalletFollowState.from_payload(
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
