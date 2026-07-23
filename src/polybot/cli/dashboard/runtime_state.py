"""Runtime identity and lifecycle state for the terminal dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import monotonic

from polybot.cli.observability.events import RuntimeState
from polybot.framework.config.models import BotMode


@dataclass(slots=True)
class DashboardRuntime:
    """The runtime facts displayed independently of stream activity."""

    name: str = "-"
    mode: BotMode | None = None
    lifecycle: RuntimeState = RuntimeState.STARTING
    started_at_monotonic: float | None = None
    initial_cash_usdc: Decimal | None = None

    def start(
        self,
        *,
        name: str,
        mode: BotMode,
        initial_cash_usdc: Decimal,
        occurred_at_monotonic: float,
    ) -> None:
        self.name = name
        self.mode = mode
        self.initial_cash_usdc = initial_cash_usdc
        self.started_at_monotonic = occurred_at_monotonic
        self.lifecycle = RuntimeState.STARTING

    def transition_to(self, lifecycle: RuntimeState) -> None:
        self.lifecycle = lifecycle

    def fail(self) -> None:
        self.lifecycle = RuntimeState.FAILED

    def uptime_seconds(self, now_monotonic: float | None = None) -> int:
        if self.started_at_monotonic is None:
            return 0
        current = monotonic() if now_monotonic is None else now_monotonic
        return max(0, int(current - self.started_at_monotonic))
