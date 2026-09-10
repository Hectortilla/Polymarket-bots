"""Lease-fenced latest feed observations, separate from generic event publication."""

import asyncio

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.events.contracts import LiveStreamHealthEvent
from api.events.health.store import FeedHealthStore
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.runs.lease import ExecutionLease


class RunHealthWriter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        redis: Redis,
        lease: ExecutionLease | None,
    ) -> None:
        self._sessions = sessions
        self._store = FeedHealthStore(redis)
        self._lease = lease

    async def record(self, event: LiveStreamHealthEvent) -> None:
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            async with self._sessions() as session:
                if self._lease is not None:
                    await self._lease.require(session, event.run_id)
                await self._store.record(event)
