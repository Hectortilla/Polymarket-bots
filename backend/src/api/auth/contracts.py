"""Secret-safe HTTP credential ingress and current-user response."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from api.auth.credential_input import EmailAddress, ExistingPassword, Password
from api.auth.models import UserRow


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: EmailAddress


class Credentials(EmailRequest):
    password: Password


class LoginCredentials(EmailRequest):
    password: ExistingPassword


class CurrentUser(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    email: str
    can_launch_runs: bool = Field(exclude=True)

    @classmethod
    def from_model(cls, user: UserRow) -> "CurrentUser":
        return cls(
            id=user.id,
            email=user.email,
            can_launch_runs=user.can_launch_runs,
        )


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    logged_out: Literal[True]
