"""Bot-authored runtime activity contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Protocol


class ActivitySeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


def validate_activity_message(message: object) -> None:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("activity messages must be non-empty strings")


@dataclass(frozen=True, slots=True)
class BotActivityEvent:
    message: str
    severity: ActivitySeverity = ActivitySeverity.INFO
    occurred_at_monotonic_seconds: float = field(default_factory=monotonic)

    def __post_init__(self) -> None:
        validate_activity_message(self.message)
        if not isinstance(self.severity, ActivitySeverity):
            raise ValueError("activity severity must be an ActivitySeverity")


class ActivitySink(Protocol):
    async def emit(
        self,
        message: str,
        *,
        severity: ActivitySeverity = ActivitySeverity.INFO,
    ) -> None: ...


class NullActivitySink:
    async def emit(
        self,
        message: str,
        *,
        severity: ActivitySeverity = ActivitySeverity.INFO,
    ) -> None:
        return None
