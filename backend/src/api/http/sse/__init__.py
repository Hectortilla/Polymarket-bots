"""Authorized ordered durable replay with replaceable live snapshots."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from time import monotonic
from uuid import UUID

from fastapi import Request
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.streams import StreamAuthorization
from api.events.views import EventView
from api.http.sse.frames import SSE_IDLE_COMMENT
from api.http.sse.hub import LiveSubscriptionHub
from api.http.sse.mailbox import LiveFrame
from api.http.sse.policy import SSE_RECONCILIATION_SECONDS
from api.http.sse.replay import RunEventReplay

LOGGER = logging.getLogger(__name__)


class RunEventStreamer:
    def __init__(
        self,
        run_id: UUID,
        request: Request,
        session_factory: async_sessionmaker[AsyncSession],
        authorization: StreamAuthorization,
        *,
        hub: LiveSubscriptionHub,
        view: EventView = EventView.ACTIVITY,
    ) -> None:
        self._authorization = authorization
        self._run_id, self._request = run_id, request
        self._replay = RunEventReplay(run_id, session_factory, view=view)
        self._hub = hub

    async def stream(self, after_event_id: int) -> AsyncIterator[str | bytes]:
        try:
            async with aclosing(self._stream_frames(after_event_id)) as frames:
                async for frame, terminal in frames:
                    if terminal:
                        self._hub.terminal(self._run_id)
                    if not await self._authorization.allowed():
                        return
                    if isinstance(frame, LiveFrame):
                        if not self._hub.is_terminal(self._run_id) and frame.fresh():
                            yield frame.data
                    else:
                        yield frame
                    if terminal:
                        return
        except (SQLAlchemyError, RedisError, TimeoutError):
            LOGGER.warning(
                "run event stream ended because a required service is unavailable"
            )

    async def _stream_frames(
        self, cursor: int
    ) -> AsyncIterator[tuple[str | LiveFrame, bool]]:
        if not await self._authorization.allowed():
            return
        async for frame, cursor, terminal in self._replay.frames_after(cursor):
            yield frame, terminal
            if terminal:
                return
        mailbox = await self._hub.attach(self._run_id)
        try:
            # Flush an empty stream through HTTP proxies without waiting for a
            # live frame or the independent durable reconciliation deadline.
            yield SSE_IDLE_COMMENT, False
            reconcile_at = monotonic()
            durable_wake = True
            while not await self._request.is_disconnected():
                if not await self._authorization.allowed():
                    return
                if durable_wake or monotonic() >= reconcile_at:
                    async for frame, cursor, terminal in self._replay.frames_after(
                        cursor
                    ):
                        yield frame, terminal
                        if terminal:
                            return
                    reconcile_at = monotonic() + SSE_RECONCILIATION_SECONDS
                try:
                    live, durable_wake, closed = await asyncio.wait_for(
                        mailbox.next(), timeout=max(0, reconcile_at - monotonic())
                    )
                except TimeoutError:
                    durable_wake = True
                    yield SSE_IDLE_COMMENT, False
                    continue
                if closed:
                    return
                if durable_wake:
                    # Replay before any advisory frame from the same wake. The
                    # pending frame can be replaced; committed records cannot.
                    continue
                if live is not None:
                    yield live, False
        finally:
            await self._hub.detach(self._run_id, mailbox)
