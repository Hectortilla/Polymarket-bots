"""Committed event persistence followed by Redis wake-up publication."""

from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot_control_plane.events.channels import (
    encode_durable_wake_frame,
    encode_live_event_frame,
    run_event_channel,
)
from polybot_control_plane.events.contracts import (
    DurableEvent,
    LiveRunEvent,
    PersistedDurableEvent,
)
from polybot_control_plane.events.ids import require_persisted_event_id
from polybot_control_plane.events.store import EventStore


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
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis

    async def append(self, event: DurableEvent) -> PersistedDurableEvent:
        async with self._session_factory() as session:
            stored = await EventStore(session).append(event)
        event_id = require_persisted_event_id(stored.id)
        await publish_durable_wake(self._redis, stored.run_id, event_id)
        return stored

    async def publish_live(self, event: LiveRunEvent) -> None:
        await self._redis.publish(
            run_event_channel(event.run_id),
            encode_live_event_frame(event),
        )
