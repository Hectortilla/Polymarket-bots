"""Worker-owned lifecycle and per-registration publication handles."""

from __future__ import annotations

import asyncio
from datetime import datetime
from time import monotonic
from uuid import UUID

from polybot.dashboard.contracts import DashboardSample
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.events.contracts import LiveRunSnapshot
from api.events.contracts.payloads.lifecycle import FeedObservation
from api.events.health.store import FeedHealthStore

from .clock import ShardClock
from .contracts import RegisteredRun
from .metrics import LiveMetric, LiveMetrics
from .permits import LivePermitRefresher
from .policy import LIVE_METRICS_SECONDS
from .publisher import LiveSnapshotPublisher
from .redis import LiveRedisBoundary
from .routing import LiveShardRouter


class WorkerLiveTelemetry:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        router: LiveShardRouter,
        clients: tuple[Redis, ...],
        *,
        lease_seconds: float,
    ) -> None:
        self.metrics = LiveMetrics()
        clocks = tuple(ShardClock() for _ in router.shards)
        self.permits = LivePermitRefresher(
            sessions,
            router,
            clients,
            lease_seconds=lease_seconds,
            clocks=clocks,
            metrics=self.metrics,
        )
        self.publisher = LiveSnapshotPublisher(
            router,
            self.permits,
            LiveRedisBoundary(router, clients, clocks),
            FeedHealthStore(router, clients),
            clocks,
            self.metrics,
        )
        self._metrics_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.permits.start()
        await self.publisher.start()
        if self._metrics_task is None:
            self._metrics_task = asyncio.create_task(self._report_metrics())

    async def close(self) -> None:
        await self.publisher.close()
        await self.permits.close()
        if self._metrics_task is not None:
            self._metrics_task.cancel()
            await asyncio.gather(self._metrics_task, return_exceptions=True)
            self._metrics_task = None
        self.metrics.emit("worker")

    def for_execution(self, run_id: UUID, execution_token: UUID) -> RunLiveTelemetry:
        registration = self.permits.register(run_id, execution_token)
        self.publisher.register(registration)
        return RunLiveTelemetry(self, registration)

    def unregister(self, registration: RegisteredRun) -> None:
        self.publisher.unregister(registration)
        self.permits.unregister(registration.run_id, registration.registration)

    async def _report_metrics(self) -> None:
        while True:
            deadline = monotonic() + LIVE_METRICS_SECONDS
            await asyncio.sleep(LIVE_METRICS_SECONDS)
            self.metrics.observe(
                LiveMetric.EVENT_LOOP_LAG_SECONDS, max(0, monotonic() - deadline)
            )
            self.publisher.measure_slots()
            self.metrics.emit("worker")


class RunLiveTelemetry:
    def __init__(self, owner: WorkerLiveTelemetry, registration: RegisteredRun) -> None:
        self._owner = owner
        self._registration = registration
        self._snapshot_sequence = 0
        self._health_sequence = 0
        self._health_observed_at: datetime | None = None
        self._closed = False

    def publish(
        self,
        sample: DashboardSample,
        *,
        occurred_at: datetime,
        health: FeedObservation | None,
    ) -> None:
        if self._closed:
            return
        self._snapshot_sequence += 1
        self._owner.publisher.submit(
            self._registration,
            LiveRunSnapshot.from_sample(
                self._registration.run_id,
                sample,
                occurred_at=occurred_at,
                generation=self._registration.registration,
                sequence=self._snapshot_sequence,
                health=health,
            ),
        )

    def watched(self) -> bool:
        return not self._closed and self._owner.publisher.watched(self._registration)

    def record_health(self, observation: FeedObservation) -> bool:
        if self._closed:
            return False
        if (
            self._health_observed_at is not None
            and observation.observed_at <= self._health_observed_at
        ):
            return True
        sequence = self._health_sequence + 1
        if not self._owner.publisher.submit_health(
            self._registration, observation, sequence
        ):
            return False
        self._health_sequence = sequence
        self._health_observed_at = observation.observed_at
        return True

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._owner.unregister(self._registration)
