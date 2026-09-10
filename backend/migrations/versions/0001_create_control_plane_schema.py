"""Create the complete initial control-plane schema for fresh databases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.auth.policy import EMAIL_MAX_LENGTH
from api.auth.recovery.database_types import ACCOUNT_TOKEN_PURPOSE_TYPE
from api.auth.recovery.schema import (
    ACCOUNT_TOKENS_TABLE,
    TOKEN_EXPIRY_INDEX,
    TOKEN_USER_PURPOSE_CONSTRAINT,
    TokenColumn,
)
from api.auth.schema import (
    OWNER_USER_ID_COLUMN,
    SESSION_EXPIRY_INDEX,
    SESSION_USER_INDEX,
    SESSIONS_TABLE,
    USER_ID_REFERENCE,
    USERS_EMAIL_CONSTRAINT_NAME,
    USERS_TABLE,
    SessionColumn,
    UserColumn,
)
from api.auth.token_digest import AUTH_TOKEN_DIGEST_HEX_LENGTH
from api.bots.revisions import FIRST_GRAPH_REVISION_NUMBER
from api.bots.schema import (
    BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME,
    BOT_GRAPH_REVISIONS_TABLE_NAME,
    BOTS_TABLE_NAME,
    BotColumn,
    BotGraphRevisionColumn,
)
from api.events.schema import (
    RUN_EVENTS_CURSOR_INDEX_NAME,
    RUN_EVENTS_TABLE_NAME,
    EventColumn,
    event_kind_column_type,
)
from api.graph_templates.names import GRAPH_TEMPLATE_NAME_MAX_LENGTH
from api.graph_templates.schema import (
    GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
    GRAPH_TEMPLATES_TABLE_NAME,
    GraphTemplateColumn,
)
from api.lifecycle.schema import (
    DELETION_REQUEST_TIME_INDEX,
    DELETION_REQUESTS_TABLE,
    HISTORY_EXPIRED_AT_COLUMN,
    RESTORE_QUARANTINED_AT_COLUMN,
    DeletionColumn,
)
from api.operations.database_types import AUDIT_ACTION_TYPE, AUDIT_OUTCOME_TYPE
from api.operations.schema import (
    AUDIT_TABLE,
    AUDIT_TIME_INDEX,
    CONTROL_TABLE,
    DEFAULT_ADMISSIONS_PAUSED,
    GLOBAL_OPERATION_CONTROL_ROW_ID,
)
from api.operations.schema import OperationControlColumn as ControlColumn
from api.operations.schema import OperatorAuditColumn as AuditColumn
from api.runs.schema import (
    RUN_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    RUN_LAUNCH_KEY_CONSTRAINT_NAME,
    RUNS_TABLE_NAME,
    RunColumn,
    run_status_column_type,
)
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        USERS_TABLE,
        sa.Column(UserColumn.ID, postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(UserColumn.EMAIL, sa.String(EMAIL_MAX_LENGTH), nullable=False),
        sa.Column(UserColumn.PASSWORD_HASH, sa.String(), nullable=False),
        sa.Column(UserColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            UserColumn.EMAIL_VERIFIED_AT, sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            UserColumn.VERIFICATION_REQUIRED,
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(UserColumn.SUSPENDED_AT, sa.DateTime(timezone=True)),
        sa.Column(RESTORE_QUARANTINED_AT_COLUMN, sa.DateTime(timezone=True)),
        sa.UniqueConstraint(UserColumn.EMAIL, name=USERS_EMAIL_CONSTRAINT_NAME),
    )
    op.create_table(
        SESSIONS_TABLE,
        sa.Column(
            SessionColumn.TOKEN_DIGEST,
            sa.String(AUTH_TOKEN_DIGEST_HEX_LENGTH),
            primary_key=True,
        ),
        sa.Column(
            SessionColumn.USER_ID,
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(USER_ID_REFERENCE),
            nullable=False,
        ),
        sa.Column(SessionColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(SessionColumn.EXPIRES_AT, sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(SESSION_USER_INDEX, SESSIONS_TABLE, [SessionColumn.USER_ID])
    op.create_index(SESSION_EXPIRY_INDEX, SESSIONS_TABLE, [SessionColumn.EXPIRES_AT])
    op.create_table(
        ACCOUNT_TOKENS_TABLE,
        sa.Column(
            TokenColumn.DIGEST,
            sa.String(AUTH_TOKEN_DIGEST_HEX_LENGTH),
            primary_key=True,
        ),
        sa.Column(
            TokenColumn.USER_ID,
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(USER_ID_REFERENCE),
            nullable=False,
        ),
        sa.Column(TokenColumn.PURPOSE, ACCOUNT_TOKEN_PURPOSE_TYPE, nullable=False),
        sa.Column(TokenColumn.EXPIRES_AT, sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            TokenColumn.USER_ID, TokenColumn.PURPOSE, name=TOKEN_USER_PURPOSE_CONSTRAINT
        ),
    )
    op.create_index(TOKEN_EXPIRY_INDEX, ACCOUNT_TOKENS_TABLE, [TokenColumn.EXPIRES_AT])
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
        sa.Column(OWNER_USER_ID_COLUMN, postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(GraphTemplateColumn.ID),
        sa.UniqueConstraint(
            OWNER_USER_ID_COLUMN,
            GraphTemplateColumn.NAME,
            name=GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
        ),
        sa.ForeignKeyConstraint(
            [OWNER_USER_ID_COLUMN],
            [USER_ID_REFERENCE],
            name=f"fk_{GRAPH_TEMPLATES_TABLE_NAME}_owner",
        ),
    )
    op.create_index(
        f"ix_{GRAPH_TEMPLATES_TABLE_NAME}_{OWNER_USER_ID_COLUMN}",
        GRAPH_TEMPLATES_TABLE_NAME,
        [OWNER_USER_ID_COLUMN],
    )
    op.create_table(
        BOTS_TABLE_NAME,
        sa.Column(BotColumn.ID, postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(BotColumn.DEFINITION_ID, sa.String(), nullable=False),
        sa.Column(
            BotColumn.CONFIG, postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(BotColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(BotColumn.UPDATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(BotColumn.DELETED_AT, sa.DateTime(timezone=True), nullable=True),
        sa.Column(OWNER_USER_ID_COLUMN, postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(BotColumn.ID),
        sa.ForeignKeyConstraint(
            [OWNER_USER_ID_COLUMN],
            [USER_ID_REFERENCE],
            name=f"fk_{BOTS_TABLE_NAME}_owner",
        ),
    )
    op.create_index(
        f"ix_{BOTS_TABLE_NAME}_{OWNER_USER_ID_COLUMN}",
        BOTS_TABLE_NAME,
        [OWNER_USER_ID_COLUMN],
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
            [BotGraphRevisionColumn.BOT_ID], [f"{BOTS_TABLE_NAME}.{BotColumn.ID}"]
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
            RunColumn.CONFIG, postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            RunColumn.BOT_GRAPH_REVISION_ID,
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(RunColumn.STATUS, run_status_column_type(), nullable=False),
        sa.Column(RunColumn.CREATED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(RunColumn.STARTED_AT, sa.DateTime(timezone=True), nullable=True),
        sa.Column(RunColumn.ENDED_AT, sa.DateTime(timezone=True), nullable=True),
        sa.Column(RunColumn.HEARTBEAT_AT, sa.DateTime(timezone=True), nullable=True),
        sa.Column(RunColumn.FAILURE_DETAIL, sa.String(), nullable=True),
        sa.Column(RunColumn.LAUNCH_KEY, postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            RunColumn.EXECUTION_TOKEN, postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            RunColumn.DELIVERY_ATTEMPTED_AT, sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(HISTORY_EXPIRED_AT_COLUMN, sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            [RunColumn.BOT_ID], [f"{BOTS_TABLE_NAME}.{BotColumn.ID}"]
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
        sa.UniqueConstraint(
            RunColumn.BOT_ID, RunColumn.LAUNCH_KEY, name=RUN_LAUNCH_KEY_CONSTRAINT_NAME
        ),
    )
    op.create_table(
        RUN_EVENTS_TABLE_NAME,
        sa.Column(
            EventColumn.ID, sa.BigInteger(), primary_key=True, autoincrement=True
        ),
        sa.Column(
            EventColumn.RUN_ID,
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{RUNS_TABLE_NAME}.{RunColumn.ID}"),
            nullable=False,
        ),
        sa.Column(EventColumn.KIND, event_kind_column_type(), nullable=False),
        sa.Column(EventColumn.OCCURRED_AT, sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            EventColumn.PAYLOAD, postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
    )
    op.create_index(
        RUN_EVENTS_CURSOR_INDEX_NAME,
        RUN_EVENTS_TABLE_NAME,
        [EventColumn.RUN_ID, EventColumn.ID],
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


def downgrade() -> None:
    op.drop_table(DELETION_REQUESTS_TABLE)
    op.drop_table(AUDIT_TABLE)
    op.drop_table(CONTROL_TABLE)
    op.drop_table(RUN_EVENTS_TABLE_NAME)
    op.drop_table(RUNS_TABLE_NAME)
    op.drop_table(BOT_GRAPH_REVISIONS_TABLE_NAME)
    op.drop_table(BOTS_TABLE_NAME)
    op.drop_table(GRAPH_TEMPLATES_TABLE_NAME)
    op.drop_table(ACCOUNT_TOKENS_TABLE)
    op.drop_table(SESSIONS_TABLE)
    op.drop_table(USERS_TABLE)
