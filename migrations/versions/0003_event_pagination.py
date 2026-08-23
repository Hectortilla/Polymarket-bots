"""Index durable events for bounded per-run cursor pagination."""

from collections.abc import Sequence

from alembic import op

from polybot_control_plane.events.schema import (
    EventColumn,
    RUN_EVENTS_CURSOR_INDEX_NAME,
    RUN_EVENTS_RUN_ID_INDEX_NAME,
    RUN_EVENTS_TABLE_NAME,
)

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(RUN_EVENTS_RUN_ID_INDEX_NAME, table_name=RUN_EVENTS_TABLE_NAME)
    op.create_index(
        RUN_EVENTS_CURSOR_INDEX_NAME,
        RUN_EVENTS_TABLE_NAME,
        [EventColumn.RUN_ID, EventColumn.ID],
    )


def downgrade() -> None:
    op.drop_index(RUN_EVENTS_CURSOR_INDEX_NAME, table_name=RUN_EVENTS_TABLE_NAME)
    op.create_index(
        RUN_EVENTS_RUN_ID_INDEX_NAME,
        RUN_EVENTS_TABLE_NAME,
        [EventColumn.RUN_ID],
    )
