"""Append-only event persistence and Redis wake-up."""

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Field, SQLModel, select

from polybot_control_plane.events.contracts import DurableEvent, EventKind, FIRST_EVENT_CURSOR
from polybot_control_plane.events.schema import RUN_EVENTS_TABLE_NAME, event_kind_column_type
from polybot_control_plane.runs.schema import RunColumn, RUNS_TABLE_NAME


class EventRow(SQLModel, table=True):
    __tablename__ = RUN_EVENTS_TABLE_NAME

    id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    run_id: UUID = Field(sa_column=Column(PostgreSQLUUID(as_uuid=True), ForeignKey(f"{RUNS_TABLE_NAME}.{RunColumn.ID}"), index=True, nullable=False))
    kind: EventKind = Field(sa_column=Column(event_kind_column_type(), nullable=False))
    occurred_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    payload: dict[str, object] = Field(sa_column=Column(JSONB, nullable=False))


class EventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DurableEvent) -> DurableEvent:
        row = EventRow(
            run_id=event.run_id,
            kind=event.kind.value,
            occurred_at=event.occurred_at,
            payload=event.payload,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        stored = event.model_copy(update={"id": row.id})
        return stored

    async def append_many(self, events: Iterable[DurableEvent]) -> None:
        for event in events:
            self._session.add(
                EventRow(
                    run_id=event.run_id,
                    kind=event.kind.value,
                    occurred_at=event.occurred_at,
                    payload=event.payload,
                )
            )
        await self._session.commit()

    async def read(self, run_id: UUID, *, after_event_id: int = FIRST_EVENT_CURSOR) -> tuple[DurableEvent, ...]:
        rows = (
            await self._session.execute(
                select(EventRow)
                .where(EventRow.run_id == run_id, EventRow.id > after_event_id)
                .order_by(EventRow.id)
            )
        ).scalars()
        return tuple(
            DurableEvent(
                id=row.id,
                run_id=row.run_id,
                kind=row.kind,
                occurred_at=row.occurred_at,
                payload=row.payload,
            )
            for row in rows
        )
