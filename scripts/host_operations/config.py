"""Validate persisted host operational inputs before running commands."""

import json
from pathlib import Path
from typing import Self

from api.auth.credential_input import EmailAddress
from pydantic import ConfigDict, Field, field_validator, model_validator

from scripts.beta_backup.policy import DEFAULT_BACKUPS_ENABLED
from scripts.beta_backup.remote.config import SftpApplicationDirectory
from scripts.deployment.ingress import IngressSettings
from scripts.deployment.paths import OPERATIONS_CONFIGURATION_NAME
from scripts.private_files import PRIVATE_FILE_MODE, read_regular


class HostOperationsConfig(IngressSettings):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    backups_enabled: bool = Field(default=DEFAULT_BACKUPS_ENABLED, strict=True)
    remote: str | None = None
    alert_to: EmailAddress

    @field_validator("remote")
    @classmethod
    def private_remote(cls, value: str | None) -> str | None:
        return (
            SftpApplicationDirectory.from_remote(value).remote
            if value is not None
            else None
        )

    @model_validator(mode="after")
    def backup_destination(self) -> Self:
        if self.backups_enabled and self.remote is None:
            raise ValueError("backup remote is required when backups are enabled")
        return self

    @classmethod
    def read(cls, root: Path) -> "HostOperationsConfig":
        return cls.model_validate(
            json.loads(
                read_regular(
                    root / OPERATIONS_CONFIGURATION_NAME,
                    required_mode=PRIVATE_FILE_MODE,
                )
            )
        )
