"""Activate a digest-pinned release after forward migration or compatibility checks."""

import argparse
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from api.auth.config import AUTH_ORIGIN_ENV, AuthSettings
from api.deployment.services import APPLICATION_SERVICES
from api.deployment.settings import RELEASE_ID_ENV, RELEASE_ID_PATTERN
from dotenv import dotenv_values

REPOSITORY = Path(__file__).resolve().parents[1]
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
        self._validate()

    def activate(self, *, rollback: bool) -> None:
        self.compose("config", "--quiet")
        self.compose("up", "-d", "--no-recreate", "--wait", "postgres", "redis")
        # Close ingress before quiescing application processes; migration failure
        # leaves the service closed and preserves the database for forward repair.
        self.compose("stop", APPLICATION_SERVICES[0])
        self.compose("stop", *APPLICATION_SERVICES[1:])
        self.compose(
            "run", "--rm", "--no-deps", "migrate", "check" if rollback else "migrate"
        )
        self.compose("up", "-d", "--no-deps", "--wait", *APPLICATION_SERVICES[1:])
        self.compose("up", "-d", "--no-deps", "--wait", "entrypoint")

    def compose(self, *arguments: str) -> None:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("POLYBOT_")
        }
        subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                self.project,
                "--env-file",
                str(self.manifest),
                "-f",
                str(COMPOSE_FILE),
                *arguments,
            ],
            cwd=REPOSITORY,
            env=environment,
            check=True,
        )

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
    parser.add_argument("--project", default="polybot")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    BetaRelease(args.manifest, args.project).activate(rollback=args.rollback)


if __name__ == "__main__":
    main()
