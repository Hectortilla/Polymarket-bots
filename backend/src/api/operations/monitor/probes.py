"""Disk and Redis probe boundaries; malformed feed observations stay unavailable."""

import asyncio
import shutil
from pathlib import Path
from uuid import UUID

from redis.asyncio import Redis

from api.events.health.store import FeedHealthStore
from api.operations.alerts import ALERT_DEFINITIONS
from api.operations.measurement_contracts import RedisMeasurements
from api.operations.observations.contracts import AlertCode, Observation
from api.operations.telemetry.counters import ObservationCounters
from api.operations.telemetry.presence import WorkerPresenceStore


class StorageProbe:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def free_bytes(self) -> int:
        return (await asyncio.to_thread(shutil.disk_usage, self._path)).free


class RedisOperationProbe:
    def __init__(self, redis: Redis) -> None:
        self._presence = WorkerPresenceStore(redis)
        self._counters = ObservationCounters(redis)
        self._feeds = FeedHealthStore(redis)

    async def read(self) -> RedisMeasurements:
        return RedisMeasurements(
            live_worker_count=await self._presence.count(),
            recent_http_error_count=await self._counters.recent_count(
                Observation.HTTP_ERROR
            ),
            recent_admission_rejection_count=await self._counters.recent_count(
                Observation.ADMISSION_REJECTION
            ),
        )

    async def feed_alerts(self, active_run_ids: tuple[UUID, ...]) -> list[AlertCode]:
        alerts = []
        for run_id in active_run_ids:
            feed_health = await self._feeds.read(run_id)
            if feed_health is None:
                alerts.append(AlertCode.FEED_UNAVAILABLE)
            elif feed_health.book_stale or ALERT_DEFINITIONS[
                AlertCode.FEED_DEGRADED
            ].breached(feed_health.book_dispatch_lag_ms):
                alerts.append(AlertCode.FEED_DEGRADED)
        return alerts
