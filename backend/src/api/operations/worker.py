"""Taskiq lifecycle adapters for an independently supervised presence heartbeat."""

import asyncio
from uuid import uuid4

from redis.asyncio import Redis
from taskiq import TaskiqState

from api.execution.config import configured_redis_url
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS, REDIS_SOCKET_OPTIONS
from api.operations.observations.contracts import FailureObservation, Observation
from api.operations.observations.sink import OPERATION_LOG
from api.operations.telemetry.presence import WorkerPresenceStore
from api.operations.telemetry.presence_policy import PRESENCE_HEARTBEAT_SECONDS


async def start_worker_presence(state: TaskiqState) -> None:
    redis_url = await asyncio.to_thread(configured_redis_url)
    state.worker_presence = WorkerPresence(
        Redis.from_url(redis_url, **REDIS_SOCKET_OPTIONS)
    )
    state.worker_presence.start()


async def stop_worker_presence(state: TaskiqState) -> None:
    await state.worker_presence.stop()


class WorkerPresence:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._store = WorkerPresenceStore(redis)
        self.worker_id = uuid4()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._heartbeat())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        try:
            async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                await self._store.remove(self.worker_id)
        except Exception:
            OPERATION_LOG.emit(FailureObservation(Observation.TELEMETRY_UNAVAILABLE))
        finally:
            await self._redis.aclose()

    async def _heartbeat(self) -> None:
        while True:
            try:
                async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
                    await self._store.refresh(self.worker_id)
            except Exception:
                OPERATION_LOG.emit(
                    FailureObservation(Observation.TELEMETRY_UNAVAILABLE)
                )
            await asyncio.sleep(PRESENCE_HEARTBEAT_SECONDS)
