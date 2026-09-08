"""PostgreSQL identity and revocable opaque sessions."""

from datetime import datetime
from uuid import UUID, uuid4

from polybot.framework.clock import system_now_utc
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from api.auth.policy import EMAIL_MAX_LENGTH
from api.auth.schema import (
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


class UserRow(SQLModel, table=True):
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
            String(SESSION_DIGEST_HEX_LENGTH),
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
