"""Allow durable browser-dashboard chart samples."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from polybot_control_plane.events.schema import (
    EVENT_KIND_CONSTRAINT_NAME,
    MIGRATION_0002_EVENT_KINDS,
    MIGRATION_0004_EVENT_KINDS,
    EventColumn,
    RUN_EVENTS_TABLE_NAME,
)


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _replace_kind_constraint(MIGRATION_0004_EVENT_KINDS)


def downgrade() -> None:
    _replace_kind_constraint(MIGRATION_0002_EVENT_KINDS)


def _replace_kind_constraint(values: tuple[str, ...]) -> None:
    op.drop_constraint(
        EVENT_KIND_CONSTRAINT_NAME,
        RUN_EVENTS_TABLE_NAME,
        type_="check",
    )
    op.create_check_constraint(
        EVENT_KIND_CONSTRAINT_NAME,
        RUN_EVENTS_TABLE_NAME,
        sa.column(EventColumn.KIND).in_(values),
    )
