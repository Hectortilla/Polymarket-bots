"""Secret-safe HTTP credential ingress and current-user response."""

from typing import Literal
from uuid import UUID

from email_validator import validate_email
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from api.auth.models import UserRow
from api.auth.policy import EMAIL_MAX_LENGTH, PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(min_length=1, max_length=EMAIL_MAX_LENGTH)
    password: SecretStr = Field(
        min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = validate_email(
            value.strip(), check_deliverability=False
        ).normalized
        # Case folding can change Unicode length; validate the canonical result too.
        return validate_email(
            normalized.casefold(), check_deliverability=False
        ).normalized


class CurrentUser(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    email: str

    @classmethod
    def from_model(cls, user: UserRow) -> "CurrentUser":
        return cls(id=user.id, email=user.email)


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    logged_out: Literal[True]
