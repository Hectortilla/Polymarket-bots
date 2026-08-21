"""SQLModel row owned by paper-run persistence."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from polybot.framework.clock import system_now_utc
from polybot_control_plane.runs.schema import (
    DEFINITION_VERSION_CHECK,
    DEFINITION_VERSION_CONSTRAINT_NAME,
    RunColumn,
    RUNS_TABLE_NAME,
    run_status_column_type,
)
from polybot_control_plane.runs.status import RunStatus


class RunRow(SQLModel, table=True):
    __tablename__ = RUNS_TABLE_NAME
    __table_args__ = (
        CheckConstraint(
            DEFINITION_VERSION_CHECK,
            name=DEFINITION_VERSION_CONSTRAINT_NAME,
        ),
    )

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
    definition_version: int = Field(
        sa_column=Column(RunColumn.DEFINITION_VERSION, Integer, nullable=False)
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
