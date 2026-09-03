"""SQLModel row for editable graph templates."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from polybot.framework.clock import system_now_utc
from polybot_control_plane.graph_templates.names import (
    GRAPH_TEMPLATE_NAME_MAX_LENGTH,
)
from polybot_control_plane.graph_templates.schema import (
    GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
    GRAPH_TEMPLATES_TABLE_NAME,
    GraphTemplateColumn,
)


class GraphTemplateRow(SQLModel, table=True):
    __tablename__ = GRAPH_TEMPLATES_TABLE_NAME
    __table_args__ = (
        UniqueConstraint(
            GraphTemplateColumn.NAME,
            name=GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
        ),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            GraphTemplateColumn.ID,
            PostgreSQLUUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
    )
    name: str = Field(
        sa_column=Column(
            GraphTemplateColumn.NAME,
            String(GRAPH_TEMPLATE_NAME_MAX_LENGTH),
            nullable=False,
        )
    )
    graph: dict[str, object] = Field(
        sa_column=Column(GraphTemplateColumn.GRAPH, JSONB, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            GraphTemplateColumn.CREATED_AT,
            DateTime(timezone=True),
            nullable=False,
        ),
    )
    updated_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            GraphTemplateColumn.UPDATED_AT,
            DateTime(timezone=True),
            nullable=False,
        ),
    )
