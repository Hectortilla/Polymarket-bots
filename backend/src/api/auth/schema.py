"""Identity and ownership schema identifiers, independent of ORM registration."""

from enum import StrEnum

USERS_TABLE = "users"
SESSIONS_TABLE = "sessions"
USERS_EMAIL_CONSTRAINT_NAME = "users_email_key"
OWNER_USER_ID_COLUMN = "owner_user_id"
SESSION_USER_INDEX = "ix_sessions_user_id"
SESSION_EXPIRY_INDEX = "ix_sessions_expires_at"


class UserColumn(StrEnum):
    ID = "id"
    EMAIL = "email"
    PASSWORD_HASH = "password_hash"
    CREATED_AT = "created_at"
    EMAIL_VERIFIED_AT = "email_verified_at"
    SUSPENDED_AT = "suspended_at"
    VERIFICATION_REQUIRED = "verification_required"


class SessionColumn(StrEnum):
    TOKEN_DIGEST = "token_digest"
    USER_ID = "user_id"
    CREATED_AT = "created_at"
    EXPIRES_AT = "expires_at"


USER_ID_REFERENCE = f"{USERS_TABLE}.{UserColumn.ID}"
