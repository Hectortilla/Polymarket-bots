"""Persisted account-link identifiers."""

from enum import StrEnum

ACCOUNT_TOKENS_TABLE = "account_tokens"
TOKEN_USER_PURPOSE_CONSTRAINT = "uq_account_tokens_user_purpose"
TOKEN_EXPIRY_INDEX = "ix_account_tokens_expires_at"


class TokenColumn(StrEnum):
    DIGEST = "token_digest"
    USER_ID = "user_id"
    PURPOSE = "purpose"
    EXPIRES_AT = "expires_at"


TOKEN_PURPOSE_CONSTRAINT = "account_token_purpose"
