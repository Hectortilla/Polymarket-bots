"""Requested-scope validation for official-client payloads."""

from polybot.polymarket.wallet_activity.fields import (
    CONDITION_ID_FIELD,
    PROXY_WALLET_FIELD,
)


def require_wallet_scope(
    payloads: list[dict[str, object]],
    requested_wallet: str,
) -> None:
    normalized_wallet = requested_wallet.casefold()
    if any(
        str(payload.get(PROXY_WALLET_FIELD, "")).casefold() != normalized_wallet
        for payload in payloads
    ):
        raise ValueError("SDK response did not match the requested wallet")


def require_condition_scope(
    payloads: list[dict[str, object]],
    requested_condition_id: str,
) -> None:
    if any(
        payload.get(CONDITION_ID_FIELD) != requested_condition_id
        for payload in payloads
    ):
        raise ValueError("SDK response did not match the requested condition")
