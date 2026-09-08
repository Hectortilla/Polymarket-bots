"""SQLModel row for editable graph templates."""

from datetime import datetime
from uuid import UUID, uuid4

from polybot.framework.clock import system_now_utc
from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlmodel import Field

from api.auth.ownership import UserOwnedRow
from api.auth.schema import OWNER_USER_ID_COLUMN
from api.graph_templates.names import (
    GRAPH_TEMPLATE_NAME_MAX_LENGTH,
)
from api.graph_templates.schema import (
    GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
    GRAPH_TEMPLATES_TABLE_NAME,
    GraphTemplateColumn,
)


class GraphTemplateRow(UserOwnedRow, table=True):
    __tablename__ = GRAPH_TEMPLATES_TABLE_NAME
    __table_args__ = (
        UniqueConstraint(
            OWNER_USER_ID_COLUMN,
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
