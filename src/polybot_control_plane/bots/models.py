"""SQLModel rows for reusable bots and immutable graph revisions."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from polybot.framework.clock import system_now_utc
from polybot_control_plane.bots.schema import (
    BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME,
    BOT_GRAPH_REVISIONS_TABLE_NAME,
    BOTS_TABLE_NAME,
    BotColumn,
    BotGraphRevisionColumn,
)
from polybot_control_plane.bots.revisions import FIRST_GRAPH_REVISION_NUMBER


class BotRow(SQLModel, table=True):
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


class BotGraphRevisionRow(SQLModel, table=True):
    __tablename__ = BOT_GRAPH_REVISIONS_TABLE_NAME
    __table_args__ = (
        CheckConstraint(
            f"{BotGraphRevisionColumn.REVISION} >= {FIRST_GRAPH_REVISION_NUMBER}",
            name=BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME,
        ),
        UniqueConstraint(
            BotGraphRevisionColumn.BOT_ID,
            BotGraphRevisionColumn.REVISION,
            name=BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME,
        ),
        UniqueConstraint(
            BotGraphRevisionColumn.BOT_ID,
            BotGraphRevisionColumn.ID,
            name=BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
        ),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            BotGraphRevisionColumn.ID,
            PostgreSQLUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
    )
    bot_id: UUID = Field(
        sa_column=Column(
            BotGraphRevisionColumn.BOT_ID,
            PostgreSQLUUID(as_uuid=True),
            ForeignKey(f"{BOTS_TABLE_NAME}.{BotColumn.ID}"),
            nullable=False,
        ),
    )
    revision: int = Field(
        sa_column=Column(BotGraphRevisionColumn.REVISION, Integer, nullable=False)
    )
    graph: dict[str, object] = Field(
        sa_column=Column(BotGraphRevisionColumn.GRAPH, JSONB, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            BotGraphRevisionColumn.CREATED_AT,
            DateTime(timezone=True),
            nullable=False,
        ),
    )
