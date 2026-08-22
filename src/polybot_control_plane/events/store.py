"""Append-only PostgreSQL persistence for durable run events."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from polybot_control_plane.events.contracts import (
    DURABLE_EVENT_ADAPTER,
    DurableEvent,
    EVENT_DISCRIMINATOR_FIELD,
)
from polybot_control_plane.events.ids import FIRST_EVENT_CURSOR
from polybot_control_plane.events.models import EventRow


class EventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DurableEvent) -> DurableEvent:
        row = EventRow.from_event(event)
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return event.model_copy(update={"id": row.id})

    async def read(
        self,
        run_id: UUID,
        *,
        after_event_id: int = FIRST_EVENT_CURSOR,
    ) -> tuple[DurableEvent, ...]:
        rows = (
            await self._session.execute(
                select(EventRow)
                .where(EventRow.run_id == run_id, EventRow.id > after_event_id)
                .order_by(EventRow.id)
            )
        ).scalars()
        return tuple(
            DURABLE_EVENT_ADAPTER.validate_python(
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    EVENT_DISCRIMINATOR_FIELD: row.kind,
                    "occurred_at": row.occurred_at,
                    "payload": row.payload,
                }
            )
            for row in rows
        )
