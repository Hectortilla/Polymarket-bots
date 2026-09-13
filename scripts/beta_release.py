"""Activate a validated release after forward migration or compatibility checks."""

import argparse
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from api.deployment.services import (
    APPLICATION_SERVICES,
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)

from scripts.compose_project import DEFAULT_COMPOSE_PROJECT, ComposeProject
from scripts.deployment.attempt import AttemptPhase
from scripts.deployment.bundle import verify_directory
from scripts.deployment.dotenv import read_values
from scripts.deployment.images import ImagePolicy
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import (
    BUNDLE_DIRECTORY_ENV,
    COMPOSE_FILE,
    DEFAULT_APP_DIRECTORY,
)
from scripts.deployment.state import DeploymentState
from scripts.private_files import PRIVATE_FILE_MODE


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
        rows = subprocess.check_output(
            self.compose.command("ps", "--all", "--format", "json"),
            env=self.compose.environment,
            text=True,
            timeout=30,
        )
        records = (
            json.loads(rows)
            if rows.lstrip().startswith("[")
            else [json.loads(line) for line in rows.splitlines() if line]
        )
        services = {row["Service"]: row for row in records}
        for service in (*APPLICATION_SERVICES, POSTGRES_SERVICE, REDIS_SERVICE):
            row = services.get(service, {})
            if row.get("State") != "running" or row.get("Health", "") not in {
                "",
                "healthy",
            }:
                raise RuntimeError("required deployment service is not healthy")


def activate_bundle(app_dir: Path, bundle: Path, *, rollback: bool = False) -> None:
    images = verify_directory(bundle)
    compose_yaml = (bundle / "deploy/compose.yaml").read_bytes()
    state = DeploymentState(app_dir)
    with state.locked():
        pending = state.pending()
        if pending and pending.phase is AttemptPhase.ACTIVATED:
            state.promote(pending)
            pending = None
        base = pending.manifest if pending else state.manifest
        if base.exists():
            settings = RuntimeManifest.read(
                base, policy=ImagePolicy.REGISTRY, required_mode=PRIVATE_FILE_MODE
            )
            settings = settings.with_images(images)
            if not pending:
                settings = RuntimeManifest.from_values(
                    {
                        **settings.to_values(),
                        **read_values(
                            app_dir / "runtime.env", required_mode=PRIVATE_FILE_MODE
                        ),
                    },
                    policy=ImagePolicy.REGISTRY,
                )
        else:
            if rollback:
                raise ValueError("cannot roll back a fresh installation")
            settings = RuntimeManifest.from_values(
                {
                    **read_values(
                        app_dir / "runtime.env", required_mode=PRIVATE_FILE_MODE
                    ),
                    **images.to_values(),
                },
                policy=ImagePolicy.REGISTRY,
            )
        settings = replace(
            settings,
            extra_values={
                **settings.extra_values,
                BUNDLE_DIRECTORY_ENV: str(bundle.resolve()),
            },
        )
        if pending:
            retained = RuntimeManifest.read(
                pending.manifest,
                policy=ImagePolicy.REGISTRY,
                required_mode=PRIVATE_FILE_MODE,
            )
            if retained.images == images:
                if pending.rollback != rollback:
                    raise ValueError(
                        "pending attempt operation differs; retry its recorded operation"
                    )
                attempt = pending
            else:
                attempt = state.prepare(settings, compose_yaml, rollback=rollback)
        else:
            if (
                state.manifest.exists()
                and RuntimeManifest.read(state.manifest) == settings
                and state.compose_file.read_bytes() == compose_yaml
            ):
                release = BetaRelease.from_manifest(
                    state.manifest,
                    DEFAULT_COMPOSE_PROJECT,
                    compose_file=state.compose_file,
                )
                release.compose.require_local_docker()
                release.require_healthy()
                print("Active release is healthy; no application restart.")
                return
            attempt = state.prepare(settings, compose_yaml, rollback=rollback)
        release = BetaRelease.from_manifest(
            attempt.manifest, DEFAULT_COMPOSE_PROJECT, compose_file=attempt.compose_file
        )
        release.compose.require_local_docker()
        release.compose.run("config", "--quiet")
        release.compose.run("pull")
        state.begin_activation(attempt)
        release.activate(rollback=attempt.rollback)
        release.require_healthy()
        state.promote(state.mark_activated(attempt))
        print(f"Activated {images.source_commit}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIRECTORY)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    activate_bundle(args.app_dir, args.bundle, rollback=args.rollback)


if __name__ == "__main__":
    main()
