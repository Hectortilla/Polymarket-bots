"""Committed event persistence followed by Redis wake-up publication."""

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot_control_plane.events.channels import run_event_channel
from polybot_control_plane.events.contracts import DurableEvent
from polybot_control_plane.events.store import EventStore


class RunEventWriter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis

    async def append(self, event: DurableEvent) -> DurableEvent:
        async with self._session_factory() as session:
            stored = await EventStore(session).append(event)
        await self._redis.publish(run_event_channel(event.run_id), str(stored.id))
        return stored
