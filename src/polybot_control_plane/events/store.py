"""Append-only PostgreSQL persistence for durable run events."""

from dataclasses import dataclass
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
from polybot_control_plane.events.pagination import MAX_EVENT_PAGE_LIMIT


@dataclass(frozen=True, slots=True)
class StoredEventPage:
    events: tuple[DurableEvent, ...]
    next_before_event_id: int | None


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
        limit: int = MAX_EVENT_PAGE_LIMIT,
    ) -> tuple[DurableEvent, ...]:
        rows = tuple(
            (
                await self._session.execute(
                    select(EventRow)
                    .where(EventRow.run_id == run_id, EventRow.id > after_event_id)
                    .order_by(EventRow.id)
                    .limit(limit)
                )
            ).scalars()
        )
        return tuple(self._event_from_row(row) for row in rows)

    async def read_page(
        self,
        run_id: UUID,
        *,
        before_event_id: int | None,
        limit: int,
    ) -> StoredEventPage:
        statement = select(EventRow).where(EventRow.run_id == run_id)
        if before_event_id is not None:
            statement = statement.where(EventRow.id < before_event_id)
        rows = tuple(
            (
                await self._session.execute(
                    statement.order_by(EventRow.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        return StoredEventPage(
            events=tuple(self._event_from_row(row) for row in reversed(page_rows)),
            next_before_event_id=page_rows[-1].id if has_more else None,
        )

    @staticmethod
    def _event_from_row(row: EventRow) -> DurableEvent:
        return DURABLE_EVENT_ADAPTER.validate_python(
            {
                "id": row.id,
                "run_id": row.run_id,
                EVENT_DISCRIMINATOR_FIELD: row.kind,
                "occurred_at": row.occurred_at,
                "payload": row.payload,
            }
        )
