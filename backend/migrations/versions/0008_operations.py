"""Preserve account history and introduce durable private incident controls."""

import sqlalchemy as sa
from alembic import op
from api.auth.schema import USERS_TABLE, UserColumn
from api.operations.database_types import AUDIT_ACTION_TYPE, AUDIT_OUTCOME_TYPE
from api.operations.schema import (
    AUDIT_TABLE,
    AUDIT_TIME_INDEX,
    CONTROL_TABLE,
    DEFAULT_ADMISSIONS_PAUSED,
    GLOBAL_OPERATION_CONTROL_ROW_ID,
)
from api.operations.schema import (
    OperationControlColumn as ControlColumn,
)
from api.operations.schema import (
    OperatorAuditColumn as AuditColumn,
)
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        USERS_TABLE, sa.Column(UserColumn.SUSPENDED_AT, sa.DateTime(timezone=True))
    )
    control = op.create_table(
        CONTROL_TABLE,
        sa.Column(ControlColumn.ID, sa.Integer, primary_key=True),
        sa.Column(ControlColumn.ADMISSIONS_PAUSED, sa.Boolean, nullable=False),
    )
    op.bulk_insert(
        control,
        [
            {
                ControlColumn.ID: GLOBAL_OPERATION_CONTROL_ROW_ID,
                ControlColumn.ADMISSIONS_PAUSED: DEFAULT_ADMISSIONS_PAUSED,
            }
        ],
    )
    op.create_table(
        AUDIT_TABLE,
        sa.Column(AuditColumn.ID, postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(AuditColumn.ACTOR, sa.String, nullable=False),
        sa.Column(AuditColumn.ACTION, AUDIT_ACTION_TYPE, nullable=False),
        sa.Column(AuditColumn.TARGET, postgresql.UUID(as_uuid=True)),
        sa.Column(AuditColumn.OUTCOME, AUDIT_OUTCOME_TYPE, nullable=False),
        sa.Column(AuditColumn.OCCURRED_AT, sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(AUDIT_TIME_INDEX, AUDIT_TABLE, [AuditColumn.OCCURRED_AT])


def downgrade():
    op.drop_table(AUDIT_TABLE)
    op.drop_table(CONTROL_TABLE)
    op.drop_column(USERS_TABLE, UserColumn.SUSPENDED_AT)
