"""Redis key namespace and strict atomic-admission result contract."""

from enum import IntEnum, StrEnum
from uuid import UUID

from api.limits.errors import ResourceLimitCode, ResourceLimitError

RESOURCE_KEY_PREFIX = "polybot:resources:"


class ResourceBucket(StrEnum):
    REQUESTS = "requests"
    EXPENSIVE = "expensive"
    STREAMS = "streams"

    def keys(self, user_id: UUID) -> tuple[str, str]:
        return (
            f"{RESOURCE_KEY_PREFIX}{self}:{ResourceScope.USER}:{user_id}",
            f"{RESOURCE_KEY_PREFIX}{self}:{ResourceScope.GLOBAL}",
        )


class ResourceScope(StrEnum):
    USER = "user"
    GLOBAL = "global"


class ResourceAdmissionOutcome(IntEnum):
    ACCEPTED = 0
    USER_ALLOWANCE = 1
    GLOBAL_CAPACITY = 2

    @classmethod
    def from_redis(cls, value: object) -> "ResourceAdmissionOutcome":
        if type(value) is not int:
            raise RuntimeError("invalid shared resource admission result")
        try:
            return cls(value)
        except ValueError as error:
            raise RuntimeError("invalid shared resource admission result") from error

    def require_capacity(self, resource: str) -> None:
        if self is self.USER_ALLOWANCE:
            raise ResourceLimitError(
                ResourceLimitCode.USER_ALLOWANCE,
                f"Your {resource} allowance is full. Close unused tabs or try again shortly.",
            )
        if self is self.GLOBAL_CAPACITY:
            raise ResourceLimitError(
                ResourceLimitCode.GLOBAL_CAPACITY,
                f"Shared {resource} capacity is busy. Try again shortly.",
            )
