"""Typed resource failures, separate from HTTP and persistence implementations."""

from enum import StrEnum


class ResourceLimitCode(StrEnum):
    USER_ALLOWANCE = "user_allowance"
    GLOBAL_CAPACITY = "global_capacity"
    INCIDENT_PAUSED = "incident_paused"
    ACCOUNT_SUSPENDED = "account_suspended"
    INVALID_CONFIGURATION = "invalid_configuration"


class ResourceLimitError(Exception):
    def __init__(self, code: ResourceLimitCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
