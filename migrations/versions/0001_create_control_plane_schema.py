"""Create the current disposable alpha control-plane schema."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from polybot_control_plane.bots.revisions import FIRST_GRAPH_REVISION_NUMBER
from polybot_control_plane.bots.schema import (
    BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME,
    BOT_GRAPH_REVISIONS_TABLE_NAME,
    BOTS_TABLE_NAME,
    BotColumn,
    BotGraphRevisionColumn,
)
from polybot_control_plane.graph_templates.names import (
    GRAPH_TEMPLATE_NAME_MAX_LENGTH,
)
from polybot_control_plane.graph_templates.schema import (
    GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
    GRAPH_TEMPLATES_TABLE_NAME,
    GraphTemplateColumn,
)
from polybot_control_plane.runs.schema import (
    RUN_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    RUNS_TABLE_NAME,
    RunColumn,
    run_status_column_type,
)


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        GRAPH_TEMPLATES_TABLE_NAME,
        sa.Column(
            GraphTemplateColumn.ID, postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            GraphTemplateColumn.NAME,
            sa.String(length=GRAPH_TEMPLATE_NAME_MAX_LENGTH),
            nullable=False,
        ),
        sa.Column(
            GraphTemplateColumn.GRAPH,
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            GraphTemplateColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            GraphTemplateColumn.UPDATED_AT, sa.DateTime(timezone=True), nullable=False
        ),
        sa.PrimaryKeyConstraint(GraphTemplateColumn.ID),
        sa.UniqueConstraint(
            GraphTemplateColumn.NAME,
            name=GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
        ),
    )
    op.create_table(
        BOTS_TABLE_NAME,
        sa.Column(BotColumn.ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(BotColumn.DEFINITION_ID, sa.String(), nullable=False),
        sa.Column(
            BotColumn.CONFIG,
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(BotColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(BotColumn.UPDATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(BotColumn.ID),
    )
    op.create_table(
        BOT_GRAPH_REVISIONS_TABLE_NAME,
        sa.Column(
            BotGraphRevisionColumn.ID, postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            BotGraphRevisionColumn.BOT_ID, postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(BotGraphRevisionColumn.REVISION, sa.Integer(), nullable=False),
        sa.Column(
            BotGraphRevisionColumn.GRAPH,
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            BotGraphRevisionColumn.CREATED_AT,
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"{BotGraphRevisionColumn.REVISION} >= {FIRST_GRAPH_REVISION_NUMBER}",
            name=BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME,
        ),
        sa.ForeignKeyConstraint(
            [BotGraphRevisionColumn.BOT_ID],
            [f"{BOTS_TABLE_NAME}.{BotColumn.ID}"],
        ),
        sa.PrimaryKeyConstraint(BotGraphRevisionColumn.ID),
        sa.UniqueConstraint(
            BotGraphRevisionColumn.BOT_ID,
            BotGraphRevisionColumn.REVISION,
            name=BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME,
        ),
        sa.UniqueConstraint(
            BotGraphRevisionColumn.BOT_ID,
            BotGraphRevisionColumn.ID,
            name=BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
        ),
    )
    op.create_table(
        RUNS_TABLE_NAME,
        sa.Column(RunColumn.ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(RunColumn.BOT_ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(RunColumn.DEFINITION_ID, sa.String(), nullable=False),
        sa.Column(
            RunColumn.CONFIG,
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            RunColumn.BOT_GRAPH_REVISION_ID,
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(RunColumn.STATUS, run_status_column_type(), nullable=False),
        sa.Column(
            RunColumn.CREATED_AT,
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            RunColumn.STARTED_AT,
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            RunColumn.ENDED_AT,
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            RunColumn.HEARTBEAT_AT,
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(RunColumn.FAILURE_DETAIL, sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            [RunColumn.BOT_ID],
            [f"{BOTS_TABLE_NAME}.{BotColumn.ID}"],
        ),
        sa.ForeignKeyConstraint(
            [RunColumn.BOT_ID, RunColumn.BOT_GRAPH_REVISION_ID],
            [
                f"{BOT_GRAPH_REVISIONS_TABLE_NAME}.{BotGraphRevisionColumn.BOT_ID}",
                f"{BOT_GRAPH_REVISIONS_TABLE_NAME}.{BotGraphRevisionColumn.ID}",
            ],
            name=RUN_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
        ),
        sa.PrimaryKeyConstraint(RunColumn.ID),
    )


def downgrade() -> None:
    op.drop_table(RUNS_TABLE_NAME)
    op.drop_table(BOT_GRAPH_REVISIONS_TABLE_NAME)
    op.drop_table(BOTS_TABLE_NAME)
    op.drop_table(GRAPH_TEMPLATES_TABLE_NAME)
