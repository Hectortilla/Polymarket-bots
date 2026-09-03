"""Durable PostgreSQL replay with Redis-assisted SSE continuation."""

from collections.abc import AsyncIterator, Iterator
import logging
from uuid import UUID

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot_control_plane.events.channels import (
    decode_durable_wake_frame,
    decode_live_event_frame,
    run_event_channel,
)
from polybot_control_plane.events.contracts import (
    LiveRunEvent,
    PersistedDurableEvent,
    RunLifecycleEvent,
)
from polybot_control_plane.events.ids import require_persisted_event_id
from polybot_control_plane.events.pagination import MAX_EVENT_PAGE_LIMIT
from polybot_control_plane.events.store import EventStore


SSE_IDLE_TIMEOUT_SECONDS = 15
SSE_IDLE_COMMENT = ": keep-alive\n\n"
SSE_ID_FIELD = "id"
SSE_DATA_FIELD = "data"
SSE_FIELD_SEPARATOR = ": "
SSE_FRAME_TERMINATOR = "\n\n"
LOGGER = logging.getLogger(__name__)


class RunEventStreamer:
    """Stream one run while owning its durable and live dependencies."""

    def __init__(
        self,
        run_id: UUID,
        request: Request,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
    ) -> None:
        self._run_id = run_id
        self._request = request
        self._session_factory = session_factory
        self._redis = redis

    async def stream(self, after_event_id: int) -> AsyncIterator[str]:
        cursor = after_event_id
        async for frame, cursor, terminal in self._event_frames_after(cursor):
            yield frame
            if terminal:
                return

        pubsub = self._redis.pubsub()
        channel = run_event_channel(self._run_id)
        subscribed = False
        try:
            await pubsub.subscribe(channel)
            subscribed = True
            async for frame, cursor, terminal in self._event_frames_after(cursor):
                yield frame
                if terminal:
                    return

            while not await self._request.is_disconnected():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=SSE_IDLE_TIMEOUT_SECONDS,
                )
                if message is None:
                    yield SSE_IDLE_COMMENT
                    continue
                channel_frame = message.get("data")
                if decode_durable_wake_frame(channel_frame) is not None:
                    async for frame, cursor, terminal in self._event_frames_after(
                        cursor
                    ):
                        yield frame
                        if terminal:
                            return
                    continue
                live_event = decode_live_event_frame(channel_frame)
                if live_event is None or live_event.run_id != self._run_id:
                    LOGGER.warning(
                        "dropping malformed run event frame for run %s",
                        self._run_id,
                    )
                    continue
                yield _sse_frame(live_event)
        finally:
            try:
                if subscribed:
                    await pubsub.unsubscribe(channel)
            finally:
                await pubsub.aclose()

    async def _event_frames_after(
        self,
        after_event_id: int,
    ) -> AsyncIterator[tuple[str, int, bool]]:
        cursor = after_event_id
        while True:
            events = await self._read_events(after_event_id=cursor)
            if not events:
                return
            for frame, cursor, terminal in _event_frames(events):
                yield frame, cursor, terminal
                if terminal:
                    return
            if len(events) < MAX_EVENT_PAGE_LIMIT:
                return

    async def _read_events(
        self,
        *,
        after_event_id: int,
    ) -> tuple[PersistedDurableEvent, ...]:
        async with self._session_factory() as session:
            return await EventStore(session).read(
                self._run_id,
                after_event_id=after_event_id,
            )


def _event_frames(
    events: tuple[PersistedDurableEvent, ...],
) -> Iterator[tuple[str, int, bool]]:
    for event in events:
        event_id = require_persisted_event_id(event.id)
        terminal = isinstance(event, RunLifecycleEvent) and event.is_terminal()
        yield _sse_frame(event), event_id, terminal


def _sse_frame(event: PersistedDurableEvent | LiveRunEvent) -> str:
    persisted_id = getattr(event, "id", None)
    event_id = (
        ""
        if persisted_id is None
        else f"{SSE_ID_FIELD}{SSE_FIELD_SEPARATOR}{persisted_id}\n"
    )
    return (
        f"{event_id}{SSE_DATA_FIELD}{SSE_FIELD_SEPARATOR}{event.model_dump_json()}"
        f"{SSE_FRAME_TERMINATOR}"
    )
