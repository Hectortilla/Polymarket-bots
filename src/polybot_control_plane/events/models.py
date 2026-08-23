"""SQLModel row owned by durable run-event persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from polybot_control_plane.events.contracts import DurableEvent, EventKind
from polybot_control_plane.events.schema import (
    EventColumn,
    RUN_EVENTS_CURSOR_INDEX_NAME,
    RUN_EVENTS_TABLE_NAME,
    event_kind_column_type,
)
from polybot_control_plane.runs.schema import RunColumn, RUNS_TABLE_NAME


class EventRow(SQLModel, table=True):
    __tablename__ = RUN_EVENTS_TABLE_NAME
    __table_args__ = (
        Index(
            RUN_EVENTS_CURSOR_INDEX_NAME,
            EventColumn.RUN_ID,
            EventColumn.ID,
        ),
    )

    id: int = Field(
        sa_column=Column(
            EventColumn.ID,
            BigInteger,
            primary_key=True,
            autoincrement=True,
        )
    )
    run_id: UUID = Field(
        sa_column=Column(
            EventColumn.RUN_ID,
            PostgreSQLUUID(as_uuid=True),
            ForeignKey(f"{RUNS_TABLE_NAME}.{RunColumn.ID}"),
            nullable=False,
        )
    )
    kind: EventKind = Field(
        sa_column=Column(EventColumn.KIND, event_kind_column_type(), nullable=False)
    )
    occurred_at: datetime = Field(
        sa_column=Column(
            EventColumn.OCCURRED_AT,
            DateTime(timezone=True),
            nullable=False,
        )
    )
    payload: dict[str, object] = Field(
        sa_column=Column(EventColumn.PAYLOAD, JSONB, nullable=False)
    )

    @classmethod
    def from_event(cls, event: DurableEvent) -> "EventRow":
        return cls(
            run_id=event.run_id,
            kind=event.kind,
            occurred_at=event.occurred_at,
            payload=event.payload.model_dump(mode="json"),
        )
