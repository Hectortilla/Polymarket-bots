"""Broker decorator that emits telemetry without changing broker semantics."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from polybot.cli.observability.events import (
    BrokerFailed,
    FillCompleted,
    OrderSubmitted,
    PortfolioSnapshot,
)
from polybot.cli.observability.observer import (
    RuntimeObserver,
    emit_observer_fail_open,
)
from polybot.execution.broker import Broker
from polybot.framework.events import FillEvent, OrderRequest


class ObservableBroker(Broker):
    def __init__(
        self,
        broker: Broker,
        observer: RuntimeObserver,
        portfolio_snapshot: Callable[[], PortfolioSnapshot | None],
    ) -> None:
        self._broker = broker
        self._observer = observer
        self._portfolio_snapshot = portfolio_snapshot

    async def submit(self, order: OrderRequest) -> FillEvent:
        started_at_monotonic_seconds = monotonic()
        emit_observer_fail_open(
            self._observer,
            OrderSubmitted(order, started_at_monotonic_seconds),
        )
        try:
            fill = await self._broker.submit(order)
        except BaseException as error:
            emit_observer_fail_open(
                self._observer,
                BrokerFailed(order, f"{type(error).__name__}: {error}", monotonic()),
            )
            raise
        completed_at_monotonic_seconds = monotonic()
        try:
            portfolio = self._portfolio_snapshot()
        except Exception:
            portfolio = None
        emit_observer_fail_open(
            self._observer,
            FillCompleted(
                order=order,
                fill=fill,
                portfolio=portfolio,
                latency_ms=round(
                    (
                        completed_at_monotonic_seconds
                        - started_at_monotonic_seconds
                    )
                    * 1000
                ),
                occurred_at_monotonic_seconds=completed_at_monotonic_seconds,
            ),
        )
        return fill

    async def cancel_all(self) -> None:
        await self._broker.cancel_all()
