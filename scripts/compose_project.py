"""Docker Compose commands pinned to one manifest, project, and local socket."""

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

from scripts.deployment.paths import COMPOSE_FILE, REPOSITORY

POLYBOT_ENVIRONMENT_PREFIX = "POLYBOT_"
DEFAULT_COMPOSE_PROJECT = "polybot"
DOCKER_HOST_ENV = "DOCKER_HOST"
DOCKER_CONTEXT_ENV = "DOCKER_CONTEXT"
DOCKER_CONTEXT_TIMEOUT_SECONDS = 30
LOCAL_DOCKER_SCHEME = "unix://"


class ComposeProject:
    def __init__(
        self,
        manifest: Path,
        project: str,
        *,
        compose_file: Path = COMPOSE_FILE,
        interpolation: Mapping[str, str] | None = None,
    ) -> None:
        self.manifest = manifest.resolve()
        self.compose_file = compose_file.resolve()
        self.project = project
        self._interpolation = {
            key: value
            for key, value in (interpolation or {}).items()
            if key.startswith(POLYBOT_ENVIRONMENT_PREFIX)
        }
        self._docker_host: str | None = None
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.project) is None:
            raise ValueError("invalid Compose project name")

    def run(self, *arguments: str) -> None:
        subprocess.run(
            self.command(*arguments), cwd=REPOSITORY, env=self.environment, check=True
        )

    def require_local_docker(self) -> None:
        # Deployment and backup targets use one local Unix socket; ambient
        # context overrides must never redirect a database operation mid-workflow.
        if os.environ.get(DOCKER_HOST_ENV) or os.environ.get(DOCKER_CONTEXT_ENV):
            raise ValueError(
                "this operation requires a local Docker context without environment overrides"
            )
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            env=self.environment,
            text=True,
            timeout=DOCKER_CONTEXT_TIMEOUT_SECONDS,
        ).strip()
        if not endpoint.startswith(LOCAL_DOCKER_SCHEME):
            raise ValueError("this operation requires a local Docker Unix socket")
        self._docker_host = endpoint

    @property
    def environment(self) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(POLYBOT_ENVIRONMENT_PREFIX)
        }
        environment.update(self._interpolation)
        if self._docker_host is not None:
            environment.pop(DOCKER_CONTEXT_ENV, None)
            environment.pop(DOCKER_HOST_ENV, None)
        return environment

    def command(self, *arguments: str) -> list[str]:
        docker = ["docker"]
        if self._docker_host is not None:
            docker.extend(["--host", self._docker_host])
        return [
            *docker,
            "compose",
            "--project-name",
            self.project,
            "--env-file",
            str(self.manifest),
            "-f",
            str(self.compose_file),
            *arguments,
        ]
