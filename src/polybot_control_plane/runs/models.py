"""SQLModel row owned by paper-run persistence."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from polybot.framework.clock import system_now_utc
from polybot_control_plane.runs.schema import (
    RunColumn,
    RUNS_TABLE_NAME,
    run_status_column_type,
)
from polybot_control_plane.runs.status import RunStatus


class RunRow(SQLModel, table=True):
    __tablename__ = RUNS_TABLE_NAME

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            RunColumn.ID,
            PostgreSQLUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
    )
    definition_id: str = Field(
        sa_column=Column(RunColumn.DEFINITION_ID, String, nullable=False)
    )
    config: dict[str, object] = Field(
        sa_column=Column(RunColumn.CONFIG, JSONB, nullable=False)
    )
    status: RunStatus = Field(
        default=RunStatus.QUEUED,
        sa_column=Column(
            RunColumn.STATUS,
            run_status_column_type(),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            RunColumn.CREATED_AT,
            DateTime(timezone=True),
            nullable=False,
        ),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(RunColumn.STARTED_AT, DateTime(timezone=True)),
    )
    ended_at: datetime | None = Field(
        default=None,
        sa_column=Column(RunColumn.ENDED_AT, DateTime(timezone=True)),
    )
    heartbeat_at: datetime | None = Field(
        default=None,
        sa_column=Column(RunColumn.HEARTBEAT_AT, DateTime(timezone=True)),
    )
    failure_detail: str | None = Field(
        default=None,
        sa_column=Column(RunColumn.FAILURE_DETAIL, String, nullable=True),
    )
