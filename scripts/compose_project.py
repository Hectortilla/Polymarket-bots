"""Docker Compose commands pinned to one manifest, project, and local socket."""

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

from scripts.deployment.paths import COMPOSE_FILE, REPOSITORY
from scripts.local_docker import LocalDocker

POLYBOT_ENVIRONMENT_PREFIX = "POLYBOT_"
DEFAULT_COMPOSE_PROJECT = "polybot"


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
        self._docker: LocalDocker | None = None
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.project) is None:
            raise ValueError("invalid Compose project name")

    def run(self, *arguments: str) -> None:
        subprocess.run(
            self.command(*arguments), cwd=REPOSITORY, env=self.environment, check=True
        )

    def require_local_docker(self) -> None:
        self._docker = LocalDocker.from_context()

    @property
    def environment(self) -> dict[str, str]:
        environment = {
            key: value
            for key, value in (
                self._docker.environment if self._docker else os.environ
            ).items()
            if not key.startswith(POLYBOT_ENVIRONMENT_PREFIX)
        }
        environment.update(self._interpolation)
        return environment

    def command(self, *arguments: str) -> list[str]:
        docker = self._docker.command() if self._docker else ["docker"]
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
