"""Secret-safe account management request and response contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from api.auth.credential_input import Password
from api.auth.models import UserRow
from api.auth.recovery.policy import SessionRevocation
from api.auth.recovery.tokens import ACCOUNT_TOKEN_LENGTH, AccountToken


class SecretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class RedeemRequest(SecretRequest):
    token: SecretStr = Field(
        min_length=ACCOUNT_TOKEN_LENGTH, max_length=ACCOUNT_TOKEN_LENGTH
    )
    new_password: Password

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        AccountToken.parse(value.get_secret_value())
        return value

    @property
    def account_token(self) -> AccountToken:
        return AccountToken(self.token.get_secret_value())


class ReauthenticateRequest(SecretRequest):
    current_password: Password


class ChangePasswordRequest(ReauthenticateRequest):
    new_password: Password


class RevokeSessionsRequest(ReauthenticateRequest):
    scope: SessionRevocation


class AccountActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    accepted: Literal[True]


class AccountStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    email_verified: bool
    verification_required: bool

    @classmethod
    def from_model(cls, user: UserRow) -> "AccountStatus":
        return cls(
            email_verified=user.email_verified_at is not None,
            verification_required=user.verification_required,
        )
