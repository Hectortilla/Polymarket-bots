"""Activate a validated release after forward migration or compatibility checks."""

import argparse
from pathlib import Path

from api.deployment.services import (
    APPLICATION_SERVICES,
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)

from scripts.compose_project import DEFAULT_COMPOSE_PROJECT, ComposeProject
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import COMPOSE_FILE


class BetaRelease:
    def __init__(self, settings: RuntimeManifest, compose: ComposeProject) -> None:
        self.settings = settings
        self.compose = compose

    @classmethod
    def from_manifest(
        cls, manifest: Path, project: str, *, compose_file: Path = COMPOSE_FILE
    ) -> "BetaRelease":
        settings = RuntimeManifest.read(manifest)
        return cls(
            settings,
            ComposeProject(
                manifest,
                project,
                compose_file=compose_file,
                interpolation=settings.to_values(),
            ),
        )

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--project", default=DEFAULT_COMPOSE_PROJECT)
    parser.add_argument("--compose-file", type=Path, default=COMPOSE_FILE)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    BetaRelease.from_manifest(
        args.manifest, args.project, compose_file=args.compose_file
    ).activate(rollback=args.rollback)


if __name__ == "__main__":
    main()
