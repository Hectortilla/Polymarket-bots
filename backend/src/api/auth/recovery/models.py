"""Only digests and bounded eligibility are persisted for email links."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlmodel import Field, SQLModel

from api.auth.recovery.database_types import ACCOUNT_TOKEN_PURPOSE_TYPE
from api.auth.recovery.policy import TokenPurpose
from api.auth.recovery.schema import (
    ACCOUNT_TOKENS_TABLE,
    TOKEN_EXPIRY_INDEX,
    TOKEN_USER_PURPOSE_CONSTRAINT,
    TokenColumn,
)
from api.auth.schema import USER_ID_REFERENCE
from api.auth.token_digest import AUTH_TOKEN_DIGEST_HEX_LENGTH


class AccountTokenRow(SQLModel, table=True):
    __tablename__ = ACCOUNT_TOKENS_TABLE
    __table_args__ = (
        UniqueConstraint(
            TokenColumn.USER_ID, TokenColumn.PURPOSE, name=TOKEN_USER_PURPOSE_CONSTRAINT
        ),
        Index(TOKEN_EXPIRY_INDEX, TokenColumn.EXPIRES_AT),
    )
    token_digest: str = Field(
        repr=False,
        sa_column=Column(
            TokenColumn.DIGEST, String(AUTH_TOKEN_DIGEST_HEX_LENGTH), primary_key=True
        ),
    )
    user_id: UUID = Field(
        sa_column=Column(
            TokenColumn.USER_ID,
            PostgreSQLUUID(as_uuid=True),
            ForeignKey(USER_ID_REFERENCE),
            nullable=False,
        ),
    )
    purpose: TokenPurpose = Field(
        sa_column=Column(
            TokenColumn.PURPOSE, ACCOUNT_TOKEN_PURPOSE_TYPE, nullable=False
        )
    )
    expires_at: datetime = Field(
        sa_column=Column(
            TokenColumn.EXPIRES_AT, DateTime(timezone=True), nullable=False
        )
    )
