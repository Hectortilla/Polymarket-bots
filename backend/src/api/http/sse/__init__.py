"""Durable PostgreSQL replay with Redis-assisted SSE continuation."""

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from uuid import UUID

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.streams import StreamAuthorization
from api.events.channels import (
    decode_durable_wake_frame,
    decode_live_event_frame,
)
from api.http.sse.frames import SSE_IDLE_COMMENT, sse_frame
from api.http.sse.replay import RunEventReplay
from api.http.sse.subscription import RunSubscription

LOGGER = logging.getLogger(__name__)
SSE_IDLE_TIMEOUT_SECONDS = 15


class RunEventStreamer:
    """Stream one run while owning its durable and live dependencies."""

    def __init__(
        self,
        run_id: UUID,
        request: Request,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        authorization: StreamAuthorization,
    ) -> None:
        self._authorization = authorization
        self._run_id = run_id
        self._request = request
        self._replay = RunEventReplay(run_id, session_factory)
        self._redis = redis

    async def stream(self, after_event_id: int) -> AsyncIterator[str]:
        try:
            async with aclosing(self._stream_frames(after_event_id)) as frames:
                async for frame, terminal in frames:
                    if not await self._authorization.allowed():
                        return
                    yield frame
                    if terminal:
                        return
        except (SQLAlchemyError, RedisError):
            LOGGER.error(
                "run event stream ended because a required service is unavailable"
            )
            return

    async def _stream_frames(
        self, after_event_id: int
    ) -> AsyncIterator[tuple[str, bool]]:
        if not await self._authorization.allowed():
            return
        cursor = after_event_id
        async for frame, cursor, terminal in self._replay.frames_after(cursor):
            yield frame, terminal

        async with RunSubscription(self._redis, self._run_id) as pubsub:
            async for frame, cursor, terminal in self._replay.frames_after(cursor):
                yield frame, terminal

            while not await self._request.is_disconnected():
                if not await self._authorization.allowed():
                    return
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=SSE_IDLE_TIMEOUT_SECONDS,
                )
                if message is None:
                    yield SSE_IDLE_COMMENT, False
                    continue
                channel_frame = message.get("data")
                if decode_durable_wake_frame(channel_frame) is not None:
                    async for frame, cursor, terminal in self._replay.frames_after(
                        cursor
                    ):
                        yield frame, terminal
                    continue
                live_event = decode_live_event_frame(channel_frame)
                if live_event is None or live_event.run_id != self._run_id:
                    LOGGER.warning(
                        "dropping malformed run event frame for run %s",
                        self._run_id,
                    )
                    continue
                yield sse_frame(live_event), False
