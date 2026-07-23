"""Broker telemetry required for durable backtest results."""

from __future__ import annotations

from polybot.execution.broker import Broker
from polybot.async_io import run_blocking
from polybot.framework.clock import Clock
from polybot.framework.events import FillEvent, OrderRequest
from polybot.performance.artifacts.lifecycle import PerformanceArtifacts
from polybot.performance.valuation import PortfolioLike


class BacktestPerformanceBroker(Broker):
    def __init__(
        self,
        broker: Broker,
        *,
        clock: Clock,
        artifacts: PerformanceArtifacts,
        portfolio: PortfolioLike,
    ) -> None:
        self._broker = broker
        self._clock = clock
        self._artifacts = artifacts
        self._portfolio = portfolio

    async def submit(self, order: OrderRequest) -> FillEvent:
        submitted_at_ms = self._clock.now_ms()
        fill = await self._broker.submit(order)
        await run_blocking(
            self._artifacts.record_fill,
            submitted_at_ms=submitted_at_ms,
            order=order,
            fill=fill,
            portfolio=self._portfolio,
        )
        return fill

    async def cancel_all(self) -> None:
        await self._broker.cancel_all()
