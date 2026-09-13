"""Controller ingress for the single-host deployment inventory."""

import re
from pathlib import Path
from typing import Self

from api.auth.credential_input import EmailAddress
from api.auth.mail.config import SmtpSecurity, SmtpSettings
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scripts.beta_backup.remote.config import (
    SftpApplicationDirectory,
    validate_sftp_host,
    validate_sftp_user,
)
from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.runtime_contracts import HTTP_PORT_MAXIMUM, HTTP_PORT_MINIMUM
from scripts.deployment.tailscale import validate_private_origin

SUPPORTED_ARCHITECTURES = {"amd64": "x86_64", "arm64": "aarch64"}
SUPPORTED_DISTRIBUTION = "Debian"


class DeploymentInventory(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        hide_input_in_errors=True,
        alias_generator=lambda name: "polybot_" + name,
    )
    root: Path
    arch: str
    origin: str
    http_port: int = Field(strict=True, ge=HTTP_PORT_MINIMUM, le=HTTP_PORT_MAXIMUM)
    smtp_host: str
    smtp_port: int = Field(strict=True, ge=1, le=65535)
    smtp_security: SmtpSecurity
    smtp_from: EmailAddress
    alert_to: EmailAddress
    sftp_host: str
    sftp_port: int = Field(strict=True, ge=1, le=65535)
    sftp_user: str
    sftp_directory: str

    @field_validator("root", mode="before")
    @classmethod
    def app_directory(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"/[a-zA-Z0-9/_-]+", value) is None
            or value.rstrip("/") in {"", "/srv", "/etc", "/home"}
        ):
            raise DeploymentInputError(
                "dedicated absolute deployment directory required"
            )
        return value

    @field_validator("arch")
    @classmethod
    def architecture(cls, value: str) -> str:
        if value not in SUPPORTED_ARCHITECTURES:
            raise DeploymentInputError("unsupported deployment architecture")
        return value

    @field_validator("origin")
    @classmethod
    def origin_policy(cls, value: str) -> str:
        return validate_private_origin(value)

    @field_validator("sftp_directory")
    @classmethod
    def remote_directory(cls, value: str) -> str:
        return SftpApplicationDirectory.parse(value).path

    @field_validator("sftp_host")
    @classmethod
    def sftp_hostname(cls, value: str) -> str:
        return validate_sftp_host(value)

    @field_validator("sftp_user")
    @classmethod
    def sftp_username(cls, value: str) -> str:
        return validate_sftp_user(value)

    @field_validator("smtp_host")
    @classmethod
    def normalized_smtp_host(cls, value: str) -> str:
        return SmtpSettings.normalize_host(value)

    @model_validator(mode="after")
    def mail_transport(self) -> Self:
        SmtpSettings(
            host=self.smtp_host,
            port=self.smtp_port,
            sender=self.smtp_from,
            security=self.smtp_security,
        )
        return self

    def require_host(
        self, host_count: int, host_distribution: str, host_architecture: str
    ) -> None:
        if (
            host_count != 1
            or host_distribution != SUPPORTED_DISTRIBUTION
            or host_architecture != SUPPORTED_ARCHITECTURES[self.arch]
        ):
            raise DeploymentInputError("exactly one matching Debian host is required")

    @classmethod
    def from_ansible_inventory(cls, record: object) -> "DeploymentInventory":
        if not isinstance(record, dict) or not isinstance(record.get("_meta"), dict):
            raise DeploymentInputError("invalid Ansible inventory output")
        hosts = record["_meta"].get("hostvars")
        if not isinstance(hosts, dict) or len(hosts) != 1:
            raise DeploymentInputError("exactly one deployment host is required")
        return cls.model_validate(next(iter(hosts.values())))
