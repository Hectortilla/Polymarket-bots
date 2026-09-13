"""Validate persisted host operational inputs before running commands."""

import json
from pathlib import Path

from api.auth.credential_input import EmailAddress
from pydantic import BaseModel, ConfigDict, Field, field_validator

from scripts.beta_backup.remote.config import SftpApplicationDirectory
from scripts.deployment.paths import OPERATIONS_CONFIGURATION_NAME
from scripts.deployment.runtime_contracts import (
    DEFAULT_HTTP_PORT,
    HTTP_PORT_MAXIMUM,
    HTTP_PORT_MINIMUM,
)
from scripts.deployment.tailscale import validate_private_origin
from scripts.private_files import PRIVATE_FILE_MODE, read_regular


class HostOperationsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    remote: str
    alert_to: EmailAddress
    origin: str
    http_port: int = Field(
        default=DEFAULT_HTTP_PORT, ge=HTTP_PORT_MINIMUM, le=HTTP_PORT_MAXIMUM
    )

    @field_validator("remote")
    @classmethod
    def private_remote(cls, value: str) -> str:
        return SftpApplicationDirectory.from_remote(value).remote

    @field_validator("origin")
    @classmethod
    def private_origin(cls, value: str) -> str:
        return validate_private_origin(value)

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
