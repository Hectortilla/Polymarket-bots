"""Append-only PostgreSQL persistence for durable run events."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from polybot_control_plane.events.contracts import (
    ChartSampleEvent,
    DurableEvent,
    PERSISTED_DURABLE_EVENT_ADAPTER,
    PersistedDurableEvent,
    RunFailureEvent,
)
from polybot_control_plane.events.kinds import EVENT_DISCRIMINATOR_FIELD, EventKind
from polybot_control_plane.events.ids import FIRST_EVENT_CURSOR, is_durable_event_id
from polybot_control_plane.events.models import EventRow
from polybot_control_plane.events.pagination import (
    MAX_EVENT_PAGE_LIMIT,
    next_event_page_cursor,
)


@dataclass(frozen=True, slots=True)
class StoredEventPage:
    events: tuple[PersistedDurableEvent, ...]
    next_before_event_id: int | None


class EventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DurableEvent) -> PersistedDurableEvent:
        row = EventRow.from_event(event)
        self._session.add(row)
        await self._session.flush()
        if not is_durable_event_id(row.id):
            await self._session.rollback()
            raise ValueError("persisted durable event ID exceeds the public cursor range")
        await self._session.commit()
        await self._session.refresh(row)
        return PERSISTED_DURABLE_EVENT_ADAPTER.validate_python(
            event.model_copy(update={"id": row.id})
        )

    async def read(
        self,
        run_id: UUID,
        *,
        after_event_id: int = FIRST_EVENT_CURSOR,
        limit: int = MAX_EVENT_PAGE_LIMIT,
    ) -> tuple[PersistedDurableEvent, ...]:
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
        events = tuple(self._event_from_row(row) for row in reversed(page_rows))
        return StoredEventPage(
            events=events,
            next_before_event_id=next_event_page_cursor(
                tuple(event.id for event in events),
                has_more=has_more,
            ),
        )

    async def latest_chart_samples(
        self,
        run_ids: tuple[UUID, ...],
    ) -> dict[UUID, ChartSampleEvent]:
        return {
            event.run_id: event
            for event in await self._latest_events(run_ids, EventKind.CHART_SAMPLE)
            if isinstance(event, ChartSampleEvent)
        }

    async def latest_run_failures(
        self,
        run_ids: tuple[UUID, ...],
    ) -> dict[UUID, RunFailureEvent]:
        return {
            event.run_id: event
            for event in await self._latest_events(run_ids, EventKind.RUN_FAILURE)
            if isinstance(event, RunFailureEvent)
        }

    async def _latest_events(
        self,
        run_ids: tuple[UUID, ...],
        kind: EventKind,
    ) -> tuple[PersistedDurableEvent, ...]:
        if not run_ids:
            return ()
        rows = tuple(
            (
                await self._session.execute(
                    select(EventRow)
                    .where(
                        EventRow.run_id.in_(run_ids),
                        EventRow.kind == kind,
                    )
                    .distinct(EventRow.run_id)
                    .order_by(EventRow.run_id, EventRow.id.desc())
                )
            ).scalars()
        )
        return tuple(self._event_from_row(row) for row in rows)

    @staticmethod
    def _event_from_row(row: EventRow) -> PersistedDurableEvent:
        return PERSISTED_DURABLE_EVENT_ADAPTER.validate_python(
            {
                "id": row.id,
                "run_id": row.run_id,
                EVENT_DISCRIMINATOR_FIELD: row.kind,
                "occurred_at": row.occurred_at,
                "payload": row.payload,
            }
        )
