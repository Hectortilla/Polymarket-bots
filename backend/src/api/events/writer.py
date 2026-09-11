"""Committed event persistence followed by Redis wake-up publication."""

import asyncio
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.events.channels import encode_durable_wake_frame, run_event_channel
from api.events.contracts import (
    DurableEvent,
    LiveRunEvent,
    PersistedDurableEvent,
)
from api.events.health.writer import RunHealthWriter
from api.events.ids import require_persisted_event_id
from api.events.live_codec import encode_live_event_frame
from api.events.store import EventStore
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS
from api.runs.lease import ExecutionLease
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS


async def publish_durable_wake(
    redis: Redis,
    run_id: UUID,
    event_id: int,
) -> None:
    await redis.publish(
        run_event_channel(run_id),
        encode_durable_wake_frame(event_id),
    )


class RunEventWriter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        *,
        execution_token: UUID | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._lease = (
            None
            if execution_token is None
            else ExecutionLease(execution_token, lease_seconds)
        )

    async def append(self, event: DurableEvent) -> PersistedDurableEvent:
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            async with self._session_factory() as session:
                await self._lock_execution(session, event.run_id)
                stored = await EventStore(session).append(event)
        event_id = require_persisted_event_id(stored.id)
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            await publish_durable_wake(self._redis, stored.run_id, event_id)
        return stored

    async def publish_live(self, event: LiveRunEvent) -> None:
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            async with self._session_factory() as session:
                await self._lock_execution(session, event.run_id)
                await self._redis.publish(
                    run_event_channel(event.run_id),
                    encode_live_event_frame(event),
                )

    def health_writer(self) -> RunHealthWriter:
        """Give the observer a separately owned, identically fenced health sink."""
        return RunHealthWriter(self._session_factory, self._redis, self._lease)

    def for_execution(
        self, execution_token: UUID, lease_seconds: float
    ) -> "RunEventWriter":
        return RunEventWriter(
            self._session_factory,
            self._redis,
            execution_token=execution_token,
            lease_seconds=lease_seconds,
        )

    async def _lock_execution(self, session: AsyncSession, run_id: UUID) -> None:
        if self._lease is not None:
            await self._lease.require(session, run_id)
