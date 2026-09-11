"""Activate a digest-pinned release after forward migration or compatibility checks."""

import argparse
import re
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

from scripts.compose_project import DEFAULT_COMPOSE_PROJECT, ComposeProject

HTTPS_PORT_ENV = "POLYBOT_HTTPS_PORT"
DEFAULT_HTTPS_PORT = 8443
SECRETS_DIRECTORY_ENV = "POLYBOT_SECRETS_DIR"

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
        self._validate()
        self.compose = ComposeProject(self.manifest, project)

    def activate(self, *, rollback: bool) -> None:
        self.compose.run("config", "--quiet")
        self.compose.run(
            "up", "-d", "--no-recreate", "--wait", POSTGRES_SERVICE, REDIS_SERVICE
        )
        # Close ingress before quiescing application processes; migration failure
        # leaves the service closed and preserves the database for forward repair.
        self.compose.run("stop", APPLICATION_SERVICES[0])
        self.compose.run("stop", *APPLICATION_SERVICES[1:])
        self.compose.run(
            "run",
            "--rm",
            "--no-deps",
            DeploymentService.MIGRATE,
            DeploymentService.CHECK if rollback else DeploymentService.MIGRATE,
        )
        self.compose.run("up", "-d", "--no-deps", "--wait", *APPLICATION_SERVICES[1:])
        self.compose.run("up", "-d", "--no-deps", "--wait", ENTRYPOINT_SERVICE)

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
        port = int(self.values.get(HTTPS_PORT_ENV) or DEFAULT_HTTPS_PORT)
        if (urlsplit(origin.origin).port or 443) != port:
            raise ValueError("HTTPS port must match the browser origin")
        directory = Path(self.values.get(SECRETS_DIRECTORY_ENV) or "")
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError(
                "runtime secrets directory must be an existing absolute path"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--project", default=DEFAULT_COMPOSE_PROJECT)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    BetaRelease(args.manifest, args.project).activate(rollback=args.rollback)


if __name__ == "__main__":
    main()
