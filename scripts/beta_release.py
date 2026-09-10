"""Activate a digest-pinned release after forward migration or compatibility checks."""

import argparse
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from api.auth.config import AUTH_ORIGIN_ENV, AuthSettings
from api.deployment.services import (
    APPLICATION_SERVICES,
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)
from api.deployment.settings import RELEASE_ID_ENV, RELEASE_ID_PATTERN
from dotenv import dotenv_values

REPOSITORY = Path(__file__).resolve().parents[1]
POLYBOT_ENVIRONMENT_PREFIX = "POLYBOT_"
DEFAULT_COMPOSE_PROJECT = "polybot"
DOCKER_HOST_ENV = "DOCKER_HOST"
DOCKER_CONTEXT_ENV = "DOCKER_CONTEXT"
DOCKER_CONTEXT_TIMEOUT_SECONDS = 30
LOCAL_DOCKER_SCHEME = "unix://"

COMPOSE_FILE = REPOSITORY / "deploy" / "compose.yaml"

IMAGE_VARIABLES = (
    "POLYBOT_BACKEND_IMAGE",
    "POLYBOT_FRONTEND_IMAGE",
    "POLYBOT_POSTGRES_IMAGE",
    "POLYBOT_REDIS_IMAGE",
)


class BetaRelease:
    def __init__(self, manifest: Path, project: str) -> None:
        self.manifest = manifest.resolve()
        self.project = project
        self.values = dotenv_values(self.manifest, interpolate=False)
        self._docker_host: str | None = None
        self._validate()

    def activate(self, *, rollback: bool) -> None:
        self.compose("config", "--quiet")
        self.compose(
            "up", "-d", "--no-recreate", "--wait", POSTGRES_SERVICE, REDIS_SERVICE
        )
        # Close ingress before quiescing application processes; migration failure
        # leaves the service closed and preserves the database for forward repair.
        self.compose("stop", APPLICATION_SERVICES[0])
        self.compose("stop", *APPLICATION_SERVICES[1:])
        self.compose(
            "run",
            "--rm",
            "--no-deps",
            DeploymentService.MIGRATE,
            DeploymentService.CHECK if rollback else DeploymentService.MIGRATE,
        )
        self.compose("up", "-d", "--no-deps", "--wait", *APPLICATION_SERVICES[1:])
        self.compose("up", "-d", "--no-deps", "--wait", ENTRYPOINT_SERVICE)

    def compose(self, *arguments: str) -> None:
        subprocess.run(
            self.command(*arguments), cwd=REPOSITORY, env=self.environment, check=True
        )

    def require_local_docker(self) -> None:
        # Backup/restore targets are pinned to one local Unix socket; ambient
        # context overrides must never redirect a database operation mid-workflow.
        if os.environ.get(DOCKER_HOST_ENV) or os.environ.get(DOCKER_CONTEXT_ENV):
            raise ValueError(
                "backup/restore requires an explicit local Docker context without environment overrides"
            )
        endpoint = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            env=self.environment,
            text=True,
            timeout=DOCKER_CONTEXT_TIMEOUT_SECONDS,
        ).strip()
        if not endpoint.startswith(LOCAL_DOCKER_SCHEME):
            raise ValueError("backup/restore requires a local Docker Unix socket")
        self._docker_host = endpoint

    @property
    def environment(self) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(POLYBOT_ENVIRONMENT_PREFIX)
        }
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
            str(COMPOSE_FILE),
            *arguments,
        ]

    def _validate(self) -> None:
        for name in IMAGE_VARIABLES:
            if (
                re.fullmatch(
                    r"(?:[^\s]+@)?sha256:[a-f0-9]{64}", self.values.get(name) or ""
                )
                is None
            ):
                raise ValueError(f"{name} must be pinned by image digest")
        if (
            re.fullmatch(RELEASE_ID_PATTERN, self.values.get(RELEASE_ID_ENV) or "")
            is None
        ):
            raise ValueError("release manifest requires an immutable release ID")
        origin = AuthSettings(self.values.get(AUTH_ORIGIN_ENV) or "")
        port = int(self.values.get("POLYBOT_HTTPS_PORT") or "8443")
        if (urlsplit(origin.origin).port or 443) != port:
            raise ValueError("HTTPS port must match the browser origin")
        directory = Path(self.values.get("POLYBOT_SECRETS_DIR") or "")
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError(
                "runtime secrets directory must be an existing absolute path"
            )
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.project) is None:
            raise ValueError("invalid Compose project name")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--project", default=DEFAULT_COMPOSE_PROJECT)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    BetaRelease(args.manifest, args.project).activate(rollback=args.rollback)


if __name__ == "__main__":
    main()
