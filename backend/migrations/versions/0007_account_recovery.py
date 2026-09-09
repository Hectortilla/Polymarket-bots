"""Preserve existing account access and add digest-only recovery links."""

import sqlalchemy as sa
from alembic import op
from api.auth.recovery.database_types import ACCOUNT_TOKEN_PURPOSE_TYPE
from api.auth.recovery.schema import (
    ACCOUNT_TOKENS_TABLE,
    TOKEN_EXPIRY_INDEX,
    TOKEN_USER_PURPOSE_CONSTRAINT,
    TokenColumn,
)
from api.auth.schema import USER_ID_REFERENCE, USERS_TABLE, UserColumn
from api.auth.token_digest import AUTH_TOKEN_DIGEST_HEX_LENGTH
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        USERS_TABLE,
        sa.Column(
            UserColumn.EMAIL_VERIFIED_AT, sa.DateTime(timezone=True), nullable=True
        ),
    )
    # The temporary default preserves existing access without asserting mailbox proof.
    op.add_column(
        USERS_TABLE,
        sa.Column(
            UserColumn.VERIFICATION_REQUIRED,
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column(
        USERS_TABLE, UserColumn.VERIFICATION_REQUIRED, server_default=sa.true()
    )
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


def downgrade() -> None:
    op.drop_table(ACCOUNT_TOKENS_TABLE)
    op.drop_column(USERS_TABLE, UserColumn.VERIFICATION_REQUIRED)
    op.drop_column(USERS_TABLE, UserColumn.EMAIL_VERIFIED_AT)
