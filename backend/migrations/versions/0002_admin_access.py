"""Add explicit administrator access without promoting existing accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Freeze the migration vocabulary so future operator actions cannot change history.
PREVIOUS_ACTIONS = (
    "suspend",
    "resume-account",
    "stop-all",
    "resume-admissions",
    "stop-run",
)
ADMIN_ACTIONS = (*PREVIOUS_ACTIONS, "grant-admin", "revoke-admin")
ACTION_CONSTRAINT = "ck_operation_audit_action"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_constraint(ACTION_CONSTRAINT, "operation_audit", type_="check")
    op.create_check_constraint(
        ACTION_CONSTRAINT, "operation_audit", sa.column("action").in_(ADMIN_ACTIONS)
    )


def downgrade() -> None:
    # Refuse a lossy downgrade once admin operations exist; never erase audit history.
    op.drop_constraint(ACTION_CONSTRAINT, "operation_audit", type_="check")
    op.create_check_constraint(
        ACTION_CONSTRAINT, "operation_audit", sa.column("action").in_(PREVIOUS_ACTIONS)
    )
    op.drop_column("users", "is_admin")
