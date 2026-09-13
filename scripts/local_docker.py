"""Pin destructive local tooling to a validated Docker Unix socket."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath

DOCKER_HOST_ENV = "DOCKER_HOST"
DOCKER_CONTEXT_ENV = "DOCKER_CONTEXT"
DOCKER_CONTEXT_TIMEOUT_SECONDS = 30
LOCAL_DOCKER_SCHEME = "unix://"


@dataclass(frozen=True)
class LocalDocker:
    endpoint: str

    @classmethod
    def from_context(cls) -> "LocalDocker":
        if os.environ.get(DOCKER_HOST_ENV) or os.environ.get(DOCKER_CONTEXT_ENV):
            raise ValueError(
                "this operation requires a local Docker context without environment overrides"
            )
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            text=True,
            timeout=DOCKER_CONTEXT_TIMEOUT_SECONDS,
        ).strip()
        if (
            not endpoint.startswith(LOCAL_DOCKER_SCHEME)
            or not PurePosixPath(
                endpoint.removeprefix(LOCAL_DOCKER_SCHEME)
            ).is_absolute()
            or endpoint == LOCAL_DOCKER_SCHEME + "/"
            or any(character.isspace() or character == "\0" for character in endpoint)
        ):
            raise ValueError("this operation requires a local Docker Unix socket")
        return cls(endpoint)

    def output(self, *arguments: str, **kwargs) -> str:
        return subprocess.check_output(
            self.command(*arguments), env=self.environment, text=True, **kwargs
        ).strip()

    def command(self, *arguments: str) -> list[str]:
        return ["docker", "--host", self.endpoint, *arguments]

    @property
    def environment(self) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key not in {DOCKER_HOST_ENV, DOCKER_CONTEXT_ENV}
        }
