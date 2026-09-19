"""One process-owned, bounded PostgreSQL ownership sampler."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import timedelta
from time import monotonic, time_ns
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.runs.models import RunRow
from api.runs.status import INTERRUPTIBLE_RUN_STATUSES

from .clock import ShardClock
from .contracts import LivePermit, RegisteredRun
from .metrics import LiveMetric, LiveMetrics
from .policy import LIVE_PERMIT_SECONDS, LIVE_REFRESH_BATCH_SIZE, LIVE_REFRESH_SECONDS
from .routing import LiveShardRouter

LOGGER = logging.getLogger(__name__)


class LivePermitRefresher:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        router: LiveShardRouter,
        redis_by_shard: tuple[Redis, ...],
        *,
        lease_seconds: float,
        now: Callable[[], float] = monotonic,
        clocks: tuple[ShardClock, ...] | None = None,
        metrics: LiveMetrics | None = None,
    ) -> None:
        self._sessions = sessions
        self._router = router
        self._redis = redis_by_shard
        self._lease_seconds = lease_seconds
        self._now = now
        self._clocks = clocks or tuple(ShardClock(now=now) for _ in router.shards)
        self.metrics = metrics or LiveMetrics()
        self._registrations: dict[UUID, RegisteredRun] = {}
        self._permits: dict[UUID, LivePermit] = {}
        self._next_registration = 0
        self._task: asyncio.Task[None] | None = None
        self._refresh_lock = asyncio.Lock()

    def register(self, run_id: UUID, execution_token: UUID) -> RegisteredRun:
        # A generation belongs to the registration, never a permit or connection.
        # Microsecond epochs fit the browser's safe integer contract.
        self._next_registration = max(self._next_registration + 1, time_ns() // 1000)
        registration = RegisteredRun(
            run_id,
            execution_token,
            self._next_registration,
            self._router.shard_for(run_id).index,
        )
        self._registrations[run_id] = registration
        self._permits.pop(run_id, None)
        self.metrics.gauge(LiveMetric.REGISTRATIONS, len(self._registrations))
        return registration

    def unregister(self, run_id: UUID, registration: int) -> None:
        current = self._registrations.get(run_id)
        if current is not None and current.registration == registration:
            self._registrations.pop(run_id, None)
            self._permits.pop(run_id, None)
            self.metrics.gauge(LiveMetric.REGISTRATIONS, len(self._registrations))

    def permit_for(self, registration: RegisteredRun) -> LivePermit | None:
        permit = self._permits.get(registration.run_id)
        if (
            permit is None
            or self._registrations.get(registration.run_id) != registration
            or permit.registration != registration.registration
            or not permit.valid_at(
                self._now(), self._clocks[registration.shard_index].epoch
            )
        ):
            return None
        return permit

    @property
    def _lease_covers_permit(self) -> bool:
        return self._lease_seconds >= LIVE_PERMIT_SECONDS

    async def start(self) -> None:
        if not self._lease_covers_permit:
            LOGGER.error(
                "live telemetry disabled: execution lease is shorter than permit lifetime"
            )
            self.metrics.increment(LiveMetric.REFRESH_FAILURE)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._permits.clear()
        self._registrations.clear()
        self.metrics.gauge(LiveMetric.REGISTRATIONS, 0)

    async def refresh_once(self) -> None:
        async with self._refresh_lock:
            if not self._lease_covers_permit:
                self._permits.clear()
                return
            by_shard: dict[int, list[RegisteredRun]] = {}
            for registration in self._registrations.values():
                by_shard.setdefault(registration.shard_index, []).append(registration)
            for registrations in by_shard.values():
                for offset in range(0, len(registrations), LIVE_REFRESH_BATCH_SIZE):
                    await self._refresh_batch(
                        tuple(registrations[offset : offset + LIVE_REFRESH_BATCH_SIZE])
                    )

    async def _run(self) -> None:
        await asyncio.sleep(random.uniform(0, LIVE_REFRESH_SECONDS / 10))
        while True:
            started = self._now()
            await self.refresh_once()
            await asyncio.sleep(max(0, LIVE_REFRESH_SECONDS - (self._now() - started)))

    async def _refresh_batch(self, batch: tuple[RegisteredRun, ...]) -> None:
        started = self._now()
        shard_index = batch[0].shard_index
        clock = self._clocks[shard_index]
        self.metrics.increment(LiveMetric.REFRESH)
        try:
            async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                sample = await clock.sample(self._redis[shard_index])
                clock_epoch = clock.epoch
                async with self._sessions() as session:
                    self.metrics.increment(LiveMetric.SQL_QUERIES)
                    rows = (
                        await session.execute(
                            select(RunRow.id, RunRow.execution_token).where(
                                RunRow.id.in_(tuple(entry.run_id for entry in batch)),
                                RunRow.status.in_(INTERRUPTIBLE_RUN_STATUSES),
                                RunRow.heartbeat_at
                                >= func.clock_timestamp()
                                - timedelta(
                                    seconds=self._lease_seconds - LIVE_PERMIT_SECONDS
                                ),
                            )
                        )
                    ).all()
            execution_tokens = {row.id: row.execution_token for row in rows}
        except Exception:
            self.metrics.increment(LiveMetric.REFRESH_FAILURE)
            self._invalidate(batch)
            LOGGER.warning("live ownership sampling failed; batch permits invalidated")
            return
        finally:
            self.metrics.observe(LiveMetric.REFRESH_SECONDS, self._now() - started)
        # SQL latency never moves this deadline. Completed registrations cannot
        # be resurrected by results sampled for an earlier registration.
        local_deadline = started + LIVE_PERMIT_SECONDS
        if self._now() >= local_deadline or clock.epoch != clock_epoch:
            self._invalidate(batch)
            self.metrics.increment(LiveMetric.REFRESH_FAILURE)
            return
        for entry in batch:
            if self._registrations.get(entry.run_id) != entry:
                continue
            if execution_tokens.get(entry.run_id) != entry.execution_token:
                self._permits.pop(entry.run_id, None)
                continue
            self._permits[entry.run_id] = LivePermit(
                entry.run_id,
                entry.registration,
                entry.shard_index,
                local_deadline,
                sample.deadline(LIVE_PERMIT_SECONDS),
                clock_epoch,
            )

    def _invalidate(self, entries: tuple[RegisteredRun, ...]) -> None:
        for entry in entries:
            if self._registrations.get(entry.run_id) == entry:
                self._permits.pop(entry.run_id, None)
