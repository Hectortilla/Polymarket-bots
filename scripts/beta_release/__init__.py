"""Activate a validated release after forward migration or compatibility checks."""

from pathlib import Path

from api.deployment.services import (
    APPLICATION_SERVICES,
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)

from scripts.beta_release.health import REQUIRED_SERVICES, ComposeStatus
from scripts.compose_project import ComposeProject
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import (
    COMPOSE_FILE,
)


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

    def require_healthy(self) -> None:
        services = ComposeStatus.read(self.compose).services
        if any(
            service not in services
            or not services[service].running
            or not services[service].healthy
            for service in REQUIRED_SERVICES
        ):
            raise RuntimeError("required deployment service is not healthy")
