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


@dataclass(frozen=True, slots=True)
class BotActivityEvent:
    message: str
    severity: ActivitySeverity = ActivitySeverity.INFO
    occurred_at: float = field(default_factory=monotonic)

    def __post_init__(self) -> None:
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("activity messages must be non-empty strings")
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
