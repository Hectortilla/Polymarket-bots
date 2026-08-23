"""Add Taskiq lifecycle columns and durable run events."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from polybot_control_plane.events.schema import (
    EVENT_KIND_CONSTRAINT_NAME,
    MIGRATION_0002_EVENT_KINDS,
    EventColumn,
    RUN_EVENTS_RUN_ID_INDEX_NAME,
    RUN_EVENTS_TABLE_NAME,
)
from polybot_control_plane.runs.schema import RunColumn, RUNS_TABLE_NAME

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        RunColumn.STARTED_AT,
        RunColumn.ENDED_AT,
        RunColumn.HEARTBEAT_AT,
    ):
        op.add_column(
            RUNS_TABLE_NAME,
            sa.Column(column, sa.DateTime(timezone=True), nullable=True),
        )
    op.add_column(
        RUNS_TABLE_NAME,
        sa.Column(RunColumn.FAILURE_DETAIL, sa.String(), nullable=True),
    )
    op.create_table(
        RUN_EVENTS_TABLE_NAME,
        sa.Column(
            EventColumn.ID,
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            EventColumn.RUN_ID,
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{RUNS_TABLE_NAME}.{RunColumn.ID}"),
            nullable=False,
        ),
        sa.Column(
            EventColumn.KIND,
            sa.Enum(
                *MIGRATION_0002_EVENT_KINDS,
                name=EVENT_KIND_CONSTRAINT_NAME,
                native_enum=False,
                create_constraint=True,
                validate_strings=True,
            ),
            nullable=False,
        ),
        sa.Column(
            EventColumn.OCCURRED_AT,
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            EventColumn.PAYLOAD,
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )
    op.create_index(
        RUN_EVENTS_RUN_ID_INDEX_NAME,
        RUN_EVENTS_TABLE_NAME,
        [EventColumn.RUN_ID],
    )


def downgrade() -> None:
    op.drop_index(RUN_EVENTS_RUN_ID_INDEX_NAME, table_name=RUN_EVENTS_TABLE_NAME)
    op.drop_table(RUN_EVENTS_TABLE_NAME)
    for column in (
        RunColumn.FAILURE_DETAIL,
        RunColumn.HEARTBEAT_AT,
        RunColumn.ENDED_AT,
        RunColumn.STARTED_AT,
    ):
        op.drop_column(RUNS_TABLE_NAME, column)
