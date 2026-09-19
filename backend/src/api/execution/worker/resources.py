"""Process-owned database and publication resources for concurrent deliveries."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.deployment.settings import StartupSettings
from api.events.writer import RunEventWriter
from api.execution.policy import (
    WORKER_DELIVERY_CLEANUP_SECONDS,
    WORKER_RESOURCE_CLEANUP_SECONDS,
)
from api.io_policy import REDIS_SOCKET_OPTIONS

from .database import create_worker_database


class WorkerResources:
    def __init__(
        self,
        settings: StartupSettings,
        engine: AsyncEngine,
        sessions: async_sessionmaker[AsyncSession],
        redis: Redis,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.event_writer = RunEventWriter(sessions, redis)
        self._engine = engine
        self._redis = redis
        self._deliveries: set[asyncio.Task] = set()
        self._closing = False
        self._shutdown: asyncio.Task[None] | None = None

    @classmethod
    async def create(cls, settings: StartupSettings) -> "WorkerResources":
        engine, sessions = create_worker_database(
            settings.database_url.get_secret_value(),
            pool_size=settings.worker_database_pool_size,
        )
        redis = None
        try:
            redis = Redis.from_url(
                settings.redis_url.get_secret_value(), **REDIS_SOCKET_OPTIONS
            )
            return cls(settings, engine, sessions, redis)
        except BaseException:
            try:
                if redis is not None:
                    await redis.aclose()
            finally:
                await engine.dispose()
            raise

    @property
    def closing(self) -> bool:
        return self._closing

    @asynccontextmanager
    async def delivery(self) -> AsyncIterator[None]:
        if self._closing:
            raise RuntimeError("worker resources are shutting down")
        task = asyncio.current_task()
        if task is None or task in self._deliveries:
            raise RuntimeError("worker delivery requires its own asynchronous task")
        self._deliveries.add(task)
        try:
            yield
        finally:
            self._deliveries.remove(task)

    async def close(self) -> None:
        if asyncio.current_task() in self._deliveries:
            raise RuntimeError("a delivery cannot close worker resources")
        if self._shutdown is None:
            self._closing = True
            self._shutdown = asyncio.create_task(self._close())
        await asyncio.shield(self._shutdown)

    async def _close(self) -> None:
        errors: list[BaseException] = []
        deliveries = tuple(self._deliveries)
        for task in deliveries:
            task.cancel()
        if deliveries:
            done, pending = await asyncio.wait(
                deliveries, timeout=WORKER_DELIVERY_CLEANUP_SECONDS
            )
            for task in done:
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        errors.append(error)
            if pending:
                for task in pending:
                    task.cancel()
                errors.append(TimeoutError("worker delivery cleanup timed out"))
        # A timed-out delivery makes shutdown unclean. Dispose idle connections;
        # unresolved run ownership is left to the existing lease reconciler.
        try:
            async with asyncio.timeout(WORKER_RESOURCE_CLEANUP_SECONDS):
                results = await asyncio.gather(
                    self._redis.aclose(), self._engine.dispose(), return_exceptions=True
                )
                errors.extend(
                    result for result in results if isinstance(result, BaseException)
                )
        except TimeoutError as error:
            errors.append(error)
        if errors:
            raise BaseExceptionGroup("worker resource shutdown failed", errors)
