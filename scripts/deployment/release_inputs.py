"""Validated CI extra-vars and release identity consumed by Ansible."""

import json
from collections.abc import Mapping
from pathlib import Path

from api.deployment.release import validate_release_id
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from scripts.deployment.identity import DeploymentOperation, validate_release_tag
from scripts.private_files import write_private


class ReleaseIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)
    release_tag: str
    release_commit: str
    operation: DeploymentOperation

    @field_validator("release_tag")
    @classmethod
    def tag(cls, value: str) -> str:
        return validate_release_tag(value)

    @field_validator("release_commit")
    @classmethod
    def commit(cls, value: str) -> str:
        return validate_release_id(value)


class ReleaseInputs(ReleaseIdentity):
    release_bundle: Path
    registry_username: str = Field(min_length=1)
    registry_token: SecretStr = Field(min_length=1)

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str], release_bundle_path: Path
    ) -> "ReleaseInputs":
        values = {
            name: environment[name.upper()]
            for name in (
                "release_tag",
                "release_commit",
                "registry_username",
                "registry_token",
                "operation",
            )
        }
        return cls.model_validate(
            values | {"release_bundle": release_bundle_path.resolve()}
        )

    def write(self, destination: Path) -> None:
        values = self.model_dump(mode="json")
        values["registry_token"] = self.registry_token.get_secret_value()
        write_private(destination, json.dumps(values).encode())
