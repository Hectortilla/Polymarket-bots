"""SMTP configuration ingress with explicit TLS and local-test policy."""

import os
import re
from enum import StrEnum
from ipaddress import ip_address
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from api.auth.config import AuthSettings
from api.auth.credential_input import EmailAddress
from api.deployment.secrets import configured_secret


class SmtpSecurity(StrEnum):
    STARTTLS = "starttls"
    TLS = "tls"
    LOCAL = "local"


SMTP_HOST_ENV = "POLYBOT_SMTP_HOST"
SMTP_PORT_ENV = "POLYBOT_SMTP_PORT"
SMTP_SECURITY_ENV = "POLYBOT_SMTP_SECURITY"
SMTP_FROM_ENV = "POLYBOT_SMTP_FROM"
SMTP_USERNAME_ENV = "POLYBOT_SMTP_USERNAME"
SMTP_PASSWORD_ENV = "POLYBOT_SMTP_PASSWORD"
SMTP_TIMEOUT_SECONDS = 5


class MailConfigurationError(Exception):
    """Mail configuration is absent or invalid without exposing input values."""


class SmtpSettings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    sender: EmailAddress
    security: SmtpSecurity = SmtpSecurity.STARTTLS
    username: SecretStr | None = None
    password: SecretStr | None = None
    allow_local: bool = False

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        try:
            return str(ip_address(value))
        except ValueError:
            host = value.encode("idna").decode("ascii").lower().removesuffix(".")
            if len(host) > 253 or any(
                re.fullmatch(r"(?!-)[a-z0-9-]{1,63}(?<!-)", label) is None
                for label in host.split(".")
            ):
                raise ValueError("invalid SMTP hostname") from None
            return host

    @model_validator(mode="after")
    def validate_transport(self) -> Self:
        if (self.username is None) != (self.password is None):
            raise ValueError("SMTP credentials must be configured together")
        if self.security is SmtpSecurity.LOCAL:
            loopback = self.host == "localhost" or ip_address(self.host).is_loopback
            if not self.allow_local or not loopback:
                raise ValueError(
                    "plaintext SMTP requires explicit local HTTP and loopback"
                )
        return self

    @classmethod
    def from_env(cls, auth: AuthSettings) -> Self:
        try:
            username = configured_secret(SMTP_USERNAME_ENV)
            password = configured_secret(SMTP_PASSWORD_ENV)
            return cls(
                host=os.environ[SMTP_HOST_ENV],
                port=os.environ[SMTP_PORT_ENV],
                sender=os.environ[SMTP_FROM_ENV],
                security=os.getenv(SMTP_SECURITY_ENV, SmtpSecurity.STARTTLS),
                username=None if username is None else SecretStr(username),
                password=None if password is None else SecretStr(password),
                allow_local=auth.allow_http,
            )
        except (KeyError, ValueError, OSError):
            raise MailConfigurationError("Email delivery is not configured.") from None
