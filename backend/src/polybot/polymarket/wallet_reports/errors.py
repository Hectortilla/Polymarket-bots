"""Stable failures exposed by report adapters without vendor exceptions."""

from enum import StrEnum


class WalletReadReason(StrEnum):
    UNAVAILABLE = "wallet_report_unavailable"
    INVALID_RESPONSE = "wallet_report_invalid_response"


class WalletReadError(RuntimeError):
    def __init__(self, reason: WalletReadReason) -> None:
        self.reason = reason
        super().__init__(reason.value)
