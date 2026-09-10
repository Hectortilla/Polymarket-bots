"""Minimal deletion receipts survive eligible account data for the audit period."""

from datetime import datetime
from uuid import UUID

from polybot.framework.clock import system_now_utc
from sqlalchemy import Column, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from api.lifecycle.schema import (
    DELETION_REQUEST_TIME_INDEX,
    DELETION_REQUESTS_TABLE,
    DeletionColumn,
)


class DeletionRequestRow(SQLModel, table=True):
    __tablename__ = DELETION_REQUESTS_TABLE
    __table_args__ = (Index(DELETION_REQUEST_TIME_INDEX, DeletionColumn.REQUESTED_AT),)

    # Intentionally no user FK: only this UUID and receipt timestamps survive purge.
    user_id: UUID = Field(
        sa_column=Column(
            DeletionColumn.USER_ID, PostgreSQLUUID(as_uuid=True), primary_key=True
        )
    )
    requested_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            DeletionColumn.REQUESTED_AT, DateTime(timezone=True), nullable=False
        ),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DeletionColumn.COMPLETED_AT, DateTime(timezone=True)),
    )
