"""Users, digest-only sessions and mandatory private ownership.

Pre-auth alpha databases must be explicitly recreated before this migration.
No first-signup backfill or automatic data deletion is performed.
"""

import sqlalchemy as sa
from alembic import op
from api.auth.policy import EMAIL_MAX_LENGTH
from api.auth.schema import (
    OWNER_USER_ID_COLUMN,
    SESSION_DIGEST_HEX_LENGTH,
    SESSION_EXPIRY_INDEX,
    SESSION_USER_INDEX,
    SESSIONS_TABLE,
    USER_ID_REFERENCE,
    USERS_EMAIL_CONSTRAINT_NAME,
    USERS_TABLE,
    SessionColumn,
    UserColumn,
)
from api.bots.schema import BOTS_TABLE_NAME
from api.graph_templates.schema import (
    GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
    GRAPH_TEMPLATES_TABLE_NAME,
    GraphTemplateColumn,
)
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text(
            f"SELECT EXISTS(SELECT 1 FROM {BOTS_TABLE_NAME}) OR EXISTS(SELECT 1 FROM {GRAPH_TEMPLATES_TABLE_NAME})"
        )
    ).scalar():
        raise RuntimeError(
            "Slice 15 requires the explicitly authorized pre-auth alpha database reset"
        )
    op.create_table(
        USERS_TABLE,
        sa.Column(UserColumn.ID, UUID(as_uuid=True), primary_key=True),
        sa.Column(UserColumn.EMAIL, sa.String(EMAIL_MAX_LENGTH), nullable=False),
        sa.Column(UserColumn.PASSWORD_HASH, sa.String(), nullable=False),
        sa.Column(UserColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(UserColumn.EMAIL, name=USERS_EMAIL_CONSTRAINT_NAME),
    )
    op.create_table(
        SESSIONS_TABLE,
        sa.Column(
            SessionColumn.TOKEN_DIGEST,
            sa.String(SESSION_DIGEST_HEX_LENGTH),
            primary_key=True,
        ),
        sa.Column(
            SessionColumn.USER_ID,
            UUID(as_uuid=True),
            sa.ForeignKey(USER_ID_REFERENCE),
            nullable=False,
        ),
        sa.Column(SessionColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(SessionColumn.EXPIRES_AT, sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(SESSION_USER_INDEX, SESSIONS_TABLE, [SessionColumn.USER_ID])
    op.create_index(SESSION_EXPIRY_INDEX, SESSIONS_TABLE, [SessionColumn.EXPIRES_AT])
    for table in (BOTS_TABLE_NAME, GRAPH_TEMPLATES_TABLE_NAME):
        op.add_column(
            table, sa.Column(OWNER_USER_ID_COLUMN, UUID(as_uuid=True), nullable=False)
        )
        op.create_foreign_key(
            _owner_foreign_key_name(table),
            table,
            USERS_TABLE,
            [OWNER_USER_ID_COLUMN],
            [UserColumn.ID],
        )
        op.create_index(_owner_index_name(table), table, [OWNER_USER_ID_COLUMN])
    op.drop_constraint(
        GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME, GRAPH_TEMPLATES_TABLE_NAME, type_="unique"
    )
    op.create_unique_constraint(
        GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
        GRAPH_TEMPLATES_TABLE_NAME,
        [OWNER_USER_ID_COLUMN, GraphTemplateColumn.NAME],
    )


def downgrade() -> None:
    # Explicit downgrade removes identity; never use it on retained account data.
    op.drop_constraint(
        GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME, GRAPH_TEMPLATES_TABLE_NAME, type_="unique"
    )
    op.create_unique_constraint(
        GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
        GRAPH_TEMPLATES_TABLE_NAME,
        [GraphTemplateColumn.NAME],
    )
    for table in (GRAPH_TEMPLATES_TABLE_NAME, BOTS_TABLE_NAME):
        op.drop_index(_owner_index_name(table), table)
        op.drop_constraint(_owner_foreign_key_name(table), table, type_="foreignkey")
        op.drop_column(table, OWNER_USER_ID_COLUMN)
    op.drop_table(SESSIONS_TABLE)
    op.drop_table(USERS_TABLE)


def _owner_foreign_key_name(table: str) -> str:
    return f"fk_{table}_owner"


def _owner_index_name(table: str) -> str:
    return f"ix_{table}_{OWNER_USER_ID_COLUMN}"
