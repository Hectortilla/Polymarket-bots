"""Independent bounded probes and periodic operational alert orchestration."""

import asyncio
from dataclasses import replace
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.operations.alerts import ALERT_DEFINITIONS
from api.operations.alerts.policy import ALERT_OWNER
from api.operations.measurements import OperationMeasurements
from api.operations.monitor.probes import RedisOperationProbe, StorageProbe
from api.operations.observations.contracts import (
    AlertCode,
    AlertObservation,
    DiskObservation,
)
from api.operations.observations.sink import OPERATION_LOG
from api.operations.state import OperationControlMissing
from api.operations.storage_policy import DEFAULT_STORAGE_PROBE_PATH
from api.operations.telemetry.errors import TelemetryDataError

MONITOR_INTERVAL_SECONDS = 5


class OperationMonitor:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        redis: Redis,
        *,
        lease_seconds: float,
        storage_path: Path = DEFAULT_STORAGE_PROBE_PATH,
    ) -> None:
        self._sessions = sessions
        self._lease_seconds = lease_seconds
        self._storage = StorageProbe(storage_path)
        self._redis = RedisOperationProbe(redis)

    async def serve(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

    async def tick(self) -> tuple[AlertCode, ...]:
        alerts: list[AlertCode] = []
        database_measurements = None
        try:
            async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                async with self._sessions() as session:
                    database_measurements = await OperationMeasurements(
                        session, self._lease_seconds
                    ).read()
            OPERATION_LOG.emit(database_measurements.observation())
            alerts.extend(database_measurements.alerts())
        except OperationControlMissing:
            alerts.append(AlertCode.CONTROL_UNAVAILABLE)
        except Exception:
            alerts.append(AlertCode.DATABASE_UNAVAILABLE)
        try:
            async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                disk_free_bytes = await self._storage.free_bytes()
            OPERATION_LOG.emit(DiskObservation(disk_free_bytes))
            if ALERT_DEFINITIONS[AlertCode.STORAGE_LOW].breached(disk_free_bytes):
                alerts.append(AlertCode.STORAGE_LOW)
        except Exception:
            alerts.append(AlertCode.STORAGE_UNAVAILABLE)
        try:
            async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                redis_measurements = await self._redis.read()
                OPERATION_LOG.emit(redis_measurements.observation())
                alerts.extend(redis_measurements.alerts())
                if database_measurements is not None:
                    alerts.extend(
                        await self._redis.feed_alerts(
                            database_measurements.active_run_ids
                        )
                    )
        except TelemetryDataError:
            alerts.append(AlertCode.TELEMETRY_INVALID)
        except Exception:
            alerts.append(AlertCode.REDIS_UNAVAILABLE)
        unique_alerts = tuple(dict.fromkeys(alerts))
        for code in unique_alerts:
            definition = ALERT_DEFINITIONS[code]
            if code is AlertCode.STUCK_RUN:
                definition = replace(definition, threshold=self._lease_seconds)
            OPERATION_LOG.emit(
                AlertObservation(
                    definition.code,
                    ALERT_OWNER,
                    definition.threshold,
                    definition.unit,
                    definition.response,
                )
            )
        return unique_alerts
