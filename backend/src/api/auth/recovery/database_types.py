"""Persisted account-token purpose type shared by metadata and migration."""

from sqlalchemy import Enum

from api.auth.recovery.policy import TokenPurpose
from api.auth.recovery.schema import TOKEN_PURPOSE_CONSTRAINT

ACCOUNT_TOKEN_PURPOSE_TYPE = Enum(
    TokenPurpose,
    values_callable=lambda members: [member.value for member in members],
    name=TOKEN_PURPOSE_CONSTRAINT,
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
)
