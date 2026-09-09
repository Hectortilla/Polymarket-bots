"""Durable launch identity and delivery/ownership metadata; preserves existing runs."""

import sqlalchemy as sa
from alembic import op
from api.runs.schema import RUN_LAUNCH_KEY_CONSTRAINT_NAME, RUNS_TABLE_NAME, RunColumn
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        RUNS_TABLE_NAME,
        sa.Column(RunColumn.LAUNCH_KEY, postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        RUNS_TABLE_NAME,
        sa.Column(
            RunColumn.EXECUTION_TOKEN, postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        RUNS_TABLE_NAME,
        sa.Column(
            RunColumn.DELIVERY_ATTEMPTED_AT, sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.create_unique_constraint(
        RUN_LAUNCH_KEY_CONSTRAINT_NAME,
        RUNS_TABLE_NAME,
        [RunColumn.BOT_ID, RunColumn.LAUNCH_KEY],
    )


def downgrade():
    op.drop_constraint(RUN_LAUNCH_KEY_CONSTRAINT_NAME, RUNS_TABLE_NAME, type_="unique")
    op.drop_column(RUNS_TABLE_NAME, RunColumn.DELIVERY_ATTEMPTED_AT)
    op.drop_column(RUNS_TABLE_NAME, RunColumn.EXECUTION_TOKEN)
    op.drop_column(RUNS_TABLE_NAME, RunColumn.LAUNCH_KEY)
