"""Broker adapter that records paper fills after delegation."""

from __future__ import annotations

from polybot.execution.broker import Broker
from polybot.framework.clock import Clock
from polybot.framework.events import FillEvent, OrderRequest

from .recording import PaperPerformanceRecorder


class PaperPerformanceBroker(Broker):
    """Record the resulting fill without changing paper broker behavior."""

    def __init__(
        self,
        broker: Broker,
        *,
        recorder: PaperPerformanceRecorder,
        clock: Clock,
    ) -> None:
        self._broker = broker
        self._recorder = recorder
        self._clock = clock

    async def submit(self, order: OrderRequest) -> FillEvent:
        submitted_at_ms = self._clock.now_ms()
        fill = await self._broker.submit(order)
        self._recorder.record_fill(
            submitted_at_ms=submitted_at_ms,
            order=order,
            fill=fill,
        )
        return fill

    async def cancel_all(self) -> None:
        await self._broker.cancel_all()
