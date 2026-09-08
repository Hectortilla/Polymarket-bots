"""Paginated durable replay, scoped to an already-authorized run."""

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.events.contracts import PersistedDurableEvent
from api.events.pagination import MAX_EVENT_PAGE_LIMIT
from api.events.store import EventStore
from api.http.sse.frames import event_frames


class RunEventReplay:
    def __init__(
        self, run_id: UUID, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self._run_id = run_id
        self._session_factory = session_factory

    async def frames_after(
        self,
        after_event_id: int,
    ) -> AsyncIterator[tuple[str, int, bool]]:
        cursor = after_event_id
        while True:
            events = await self.read(after_event_id=cursor)
            if not events:
                return
            for frame, cursor, terminal in event_frames(events):
                yield frame, cursor, terminal
                if terminal:
                    return
            if len(events) < MAX_EVENT_PAGE_LIMIT:
                return

    async def read(
        self,
        *,
        after_event_id: int,
    ) -> tuple[PersistedDurableEvent, ...]:
        async with self._session_factory() as session:
            return await EventStore(session).read(
                self._run_id,
                after_event_id=after_event_id,
            )
