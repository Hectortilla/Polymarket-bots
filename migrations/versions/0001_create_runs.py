"""Create the minimal Slice 12A run row."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from polybot_control_plane.runs.schema import (
    DEFINITION_VERSION_CHECK,
    DEFINITION_VERSION_CONSTRAINT_NAME,
    RunColumn,
    RUNS_TABLE_NAME,
    run_status_column_type,
)


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        RUNS_TABLE_NAME,
        sa.Column(RunColumn.ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(RunColumn.DEFINITION_ID, sa.String(), nullable=False),
        sa.Column(RunColumn.DEFINITION_VERSION, sa.Integer(), nullable=False),
        sa.Column(
            RunColumn.CONFIG,
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(RunColumn.STATUS, run_status_column_type(), nullable=False),
        sa.Column(
            RunColumn.CREATED_AT,
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            DEFINITION_VERSION_CHECK,
            name=DEFINITION_VERSION_CONSTRAINT_NAME,
        ),
        sa.PrimaryKeyConstraint(RunColumn.ID),
    )


def downgrade() -> None:
    op.drop_table(RUNS_TABLE_NAME)
