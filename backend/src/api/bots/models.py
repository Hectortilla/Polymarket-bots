"""SQLModel rows for saved bots with complete editable configurations."""

from datetime import datetime
from uuid import UUID, uuid4

from polybot.framework.clock import system_now_utc
from sqlalchemy import (
    Column,
    DateTime,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlmodel import Field

from api.auth.ownership import UserOwnedRow
from api.bots.schema import (
    BOTS_TABLE_NAME,
    BotColumn,
)


class BotRow(UserOwnedRow, table=True):
    __tablename__ = BOTS_TABLE_NAME

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            BotColumn.ID,
            PostgreSQLUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
    )
    definition_id: str = Field(
        sa_column=Column(BotColumn.DEFINITION_ID, String, nullable=False)
    )
    config: dict[str, object] = Field(
        sa_column=Column(BotColumn.CONFIG, JSONB, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(BotColumn.CREATED_AT, DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(BotColumn.UPDATED_AT, DateTime(timezone=True), nullable=False),
    )

    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(BotColumn.DELETED_AT, DateTime(timezone=True)),
    )
