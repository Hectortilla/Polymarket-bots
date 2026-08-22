"""Durable PostgreSQL replay with Redis-assisted SSE continuation."""

from collections.abc import AsyncIterator, Iterator
import logging
from uuid import UUID

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot_control_plane.events.channels import (
    decode_durable_wake_frame,
    run_event_channel,
)
from polybot_control_plane.events.contracts import DurableEvent, RunLifecycleEvent
from polybot_control_plane.events.ids import require_persisted_event_id
from polybot_control_plane.events.store import EventStore


SSE_IDLE_TIMEOUT_SECONDS = 15
SSE_IDLE_COMMENT = ": keep-alive\n\n"
SSE_ID_FIELD = "id"
SSE_DATA_FIELD = "data"
SSE_FIELD_SEPARATOR = ": "
SSE_FRAME_TERMINATOR = "\n\n"
LOGGER = logging.getLogger(__name__)


async def stream_durable_events(
    run_id: UUID,
    *,
    after_event_id: int,
    request: Request,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> AsyncIterator[str]:
    cursor = after_event_id
    replay = await _read_events(session_factory, run_id, after_event_id=cursor)
    for frame, cursor, terminal in _event_frames(replay):
        yield frame
        if terminal:
            return

    pubsub = redis.pubsub()
    channel = run_event_channel(run_id)
    subscribed = False
    try:
        await pubsub.subscribe(channel)
        subscribed = True
        recheck = await _read_events(session_factory, run_id, after_event_id=cursor)
        for frame, cursor, terminal in _event_frames(recheck):
            yield frame
            if terminal:
                return

        while not await request.is_disconnected():
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=SSE_IDLE_TIMEOUT_SECONDS,
            )
            if message is None:
                yield SSE_IDLE_COMMENT
                continue
            if decode_durable_wake_frame(message.get("data")) is None:
                LOGGER.warning(
                    "dropping malformed durable wake frame for run %s",
                    run_id,
                )
                continue
            events = await _read_events(
                session_factory,
                run_id,
                after_event_id=cursor,
            )
            for frame, cursor, terminal in _event_frames(events):
                yield frame
                if terminal:
                    return
    finally:
        try:
            if subscribed:
                await pubsub.unsubscribe(channel)
        finally:
            await pubsub.aclose()


def _event_frames(
    events: tuple[DurableEvent, ...],
) -> Iterator[tuple[str, int, bool]]:
    for event in events:
        event_id = require_persisted_event_id(event.id)
        terminal = isinstance(event, RunLifecycleEvent) and event.is_terminal()
        yield _sse_frame(event), event_id, terminal


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    *,
    after_event_id: int,
) -> tuple[DurableEvent, ...]:
    async with session_factory() as session:
        return await EventStore(session).read(
            run_id,
            after_event_id=after_event_id,
        )


def _sse_frame(event: DurableEvent) -> str:
    return (
        f"{SSE_ID_FIELD}{SSE_FIELD_SEPARATOR}{event.id}\n"
        f"{SSE_DATA_FIELD}{SSE_FIELD_SEPARATOR}{event.model_dump_json()}"
        f"{SSE_FRAME_TERMINATOR}"
    )
