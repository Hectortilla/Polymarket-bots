"""Append-only PostgreSQL persistence for durable run events."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.events.contracts import (
    PERSISTED_DURABLE_EVENT_ADAPTER,
    ChartSampleEvent,
    DurableEvent,
    PersistedDurableEvent,
    RunFailureEvent,
)
from api.events.delivery import EventDelivery
from api.events.ids import FIRST_EVENT_CURSOR, is_durable_event_id
from api.events.kinds import EVENT_DISCRIMINATOR_FIELD, EventKind
from api.events.models import EventRow
from api.events.pagination import (
    MAX_EVENT_PAGE_LIMIT,
    next_event_page_cursor,
)
from api.events.schema import EventColumn
from api.events.views import EventView, event_selection


@dataclass(frozen=True, slots=True)
class StoredEventPage:
    events: tuple[PersistedDurableEvent, ...]
    next_before_event_id: int | None
    stream_cursor: int


class EventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DurableEvent) -> PersistedDurableEvent:
        row = EventRow.from_event(event)
        self._session.add(row)
        await self._session.flush()
        if not is_durable_event_id(row.id):
            await self._session.rollback()
            raise ValueError(
                "persisted durable event ID exceeds the public cursor range"
            )
        await self._session.commit()
        await self._session.refresh(row)
        return self._event_from_row(row)

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
        view: EventView = EventView.ACTIVITY,
    ) -> StoredEventPage:
        # Bound the query to the watermark captured before reading the page.
        # Replaying from it cannot miss commits concurrent with hydration.
        cursor = (
            await self._session.scalar(
                select(func.max(EventRow.id)).where(EventRow.run_id == run_id)
            )
            or FIRST_EVENT_CURSOR
        )
        statement = select(EventRow).where(
            EventRow.run_id == run_id, EventRow.id <= cursor, event_selection(view)
        )
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
            stream_cursor=cursor,
            next_before_event_id=next_event_page_cursor(
                tuple(event.id for event in events),
                has_more=has_more,
            ),
        )

    async def read_deliveries(
        self, run_id: UUID, *, after_event_id: int, view: EventView
    ) -> tuple[EventDelivery, ...]:
        activity_predicate = event_selection(view)
        rows = (
            await self._session.execute(
                select(EventRow, activity_predicate.label("activity"))
                .where(
                    EventRow.run_id == run_id,
                    EventRow.id > after_event_id,
                    or_(activity_predicate, event_selection(EventView.DASHBOARD)),
                )
                .order_by(EventRow.id)
                .limit(MAX_EVENT_PAGE_LIMIT)
            )
        ).all()
        return tuple(
            EventDelivery(self._event_from_row(row), not is_activity)
            for row, is_activity in rows
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
                EventColumn.ID: row.id,
                EventColumn.RUN_ID: row.run_id,
                EVENT_DISCRIMINATOR_FIELD: row.kind,
                EventColumn.OCCURRED_AT: row.occurred_at,
                EventColumn.PAYLOAD: row.payload,
            }
        )
