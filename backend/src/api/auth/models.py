"""PostgreSQL identity and revocable opaque sessions."""

from datetime import datetime
from uuid import UUID, uuid4

from polybot.framework.clock import system_now_utc
from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlmodel import Field, SQLModel

from api.auth.policy import EMAIL_MAX_LENGTH
from api.auth.schema import (
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
from api.lifecycle.schema import RESTORE_QUARANTINED_AT_COLUMN


class UserRow(SQLModel, table=True):
    model_config = ConfigDict(ignored_types=(hybrid_property,))
    __tablename__ = USERS_TABLE
    __table_args__ = (
        UniqueConstraint(UserColumn.EMAIL, name=USERS_EMAIL_CONSTRAINT_NAME),
    )
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column_kwargs={"name": UserColumn.ID},
    )
    email: str = Field(
        sa_column=Column(UserColumn.EMAIL, String(EMAIL_MAX_LENGTH), nullable=False)
    )
    password_hash: str = Field(
        repr=False, sa_column=Column(UserColumn.PASSWORD_HASH, String, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            UserColumn.CREATED_AT, DateTime(timezone=True), nullable=False
        ),
    )
    email_verified_at: datetime | None = Field(
        default=None,
        sa_column=Column(UserColumn.EMAIL_VERIFIED_AT, DateTime(timezone=True)),
    )
    verification_required: bool = Field(
        default=True,
        sa_column=Column(
            UserColumn.VERIFICATION_REQUIRED,
            Boolean,
            nullable=False,
            server_default=true(),
        ),
    )

    suspended_at: datetime | None = Field(
        default=None,
        sa_column=Column(UserColumn.SUSPENDED_AT, DateTime(timezone=True)),
    )

    restore_quarantined_at: datetime | None = Field(
        default=None,
        sa_column=Column(RESTORE_QUARANTINED_AT_COLUMN, DateTime(timezone=True)),
    )

    @hybrid_property
    def access_allowed(self) -> bool:
        # Equality intentionally serves both Python values and SQL NULL comparison.
        return (self.suspended_at == None) & (self.restore_quarantined_at == None)  # noqa: E711

    def mark_email_verified(self) -> None:
        self.email_verified_at = system_now_utc()

    @property
    def can_launch_runs(self) -> bool:
        return self.email_verified_at is not None or not self.verification_required


class SessionRow(SQLModel, table=True):
    __tablename__ = SESSIONS_TABLE
    __table_args__ = (
        Index(SESSION_USER_INDEX, SessionColumn.USER_ID),
        Index(SESSION_EXPIRY_INDEX, SessionColumn.EXPIRES_AT),
    )
    token_digest: str = Field(
        repr=False,
        sa_column=Column(
            SessionColumn.TOKEN_DIGEST,
            String(AUTH_TOKEN_DIGEST_HEX_LENGTH),
            primary_key=True,
        ),
    )
    user_id: UUID = Field(
        sa_column=Column(
            SessionColumn.USER_ID,
            PostgreSQLUUID(as_uuid=True),
            ForeignKey(USER_ID_REFERENCE),
            nullable=False,
        )
    )
    created_at: datetime = Field(
        default_factory=system_now_utc,
        sa_column=Column(
            SessionColumn.CREATED_AT, DateTime(timezone=True), nullable=False
        ),
    )
    expires_at: datetime = Field(
        sa_column=Column(
            SessionColumn.EXPIRES_AT, DateTime(timezone=True), nullable=False
        )
    )
