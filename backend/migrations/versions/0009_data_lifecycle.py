"""Preserve account data and introduce retry-safe expiry and deletion receipts."""

import sqlalchemy as sa
from alembic import op
from api.auth.schema import USERS_TABLE
from api.lifecycle.schema import DELETION_REQUEST_TIME_INDEX, DELETION_REQUESTS_TABLE
from api.lifecycle.schema import (
    HISTORY_EXPIRED_AT_COLUMN,
    RESTORE_QUARANTINED_AT_COLUMN,
    DeletionColumn,
)
from api.runs.schema import RUNS_TABLE_NAME
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        RUNS_TABLE_NAME,
        sa.Column(HISTORY_EXPIRED_AT_COLUMN, sa.DateTime(timezone=True)),
    )
    op.add_column(
        USERS_TABLE,
        sa.Column(RESTORE_QUARANTINED_AT_COLUMN, sa.DateTime(timezone=True)),
    )
    op.create_table(
        DELETION_REQUESTS_TABLE,
        sa.Column(
            DeletionColumn.USER_ID, postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            DeletionColumn.REQUESTED_AT, sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(DeletionColumn.COMPLETED_AT, sa.DateTime(timezone=True)),
    )
    op.create_index(
        DELETION_REQUEST_TIME_INDEX,
        DELETION_REQUESTS_TABLE,
        [DeletionColumn.REQUESTED_AT],
    )


def downgrade():
    op.drop_table(DELETION_REQUESTS_TABLE)
    op.drop_column(USERS_TABLE, RESTORE_QUARANTINED_AT_COLUMN)
    op.drop_column(RUNS_TABLE_NAME, HISTORY_EXPIRED_AT_COLUMN)
