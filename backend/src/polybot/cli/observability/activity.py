"""Bridge bot-authored activity into fail-open runtime observation."""

from __future__ import annotations

from polybot.cli.observability.observer import (
    RuntimeObserver,
    emit_observer_fail_open,
)
from polybot.framework.activity import ActivitySeverity, BotActivityEvent


class ObserverActivitySink:
    def __init__(self, observer: RuntimeObserver) -> None:
        self._observer = observer

    async def emit(
        self,
        message: str,
        *,
        severity: ActivitySeverity = ActivitySeverity.INFO,
    ) -> None:
        try:
            event = BotActivityEvent(message=message, severity=severity)
        except (TypeError, ValueError):
            return None
        emit_observer_fail_open(self._observer, event)
