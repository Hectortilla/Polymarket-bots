"""Durable deployment lifecycle and retry selection."""

from pathlib import Path

from scripts.beta_release import BetaRelease
from scripts.beta_release.selection import ActivationSelection
from scripts.compose_project import DEFAULT_COMPOSE_PROJECT
from scripts.deployment.attempt import AttemptPhase
from scripts.deployment.bundle.installation import InstalledBundle
from scripts.deployment.state import DeploymentState


class DeploymentActivator:
    def __init__(self, app_directory: Path) -> None:
        self.state = DeploymentState(app_directory)

    def activate(self, bundle: Path, *, rollback: bool = False) -> None:
        state = self.state
        installed = InstalledBundle.read(bundle, state.directory)
        with state.locked():
            pending = state.pending()
            if pending and pending.phase is AttemptPhase.ACTIVATED:
                state.promote(pending)
            selected = ActivationSelection.read(state, installed, rollback=rollback)
            if selected.already_active:
                release = BetaRelease.from_manifest(
                    state.manifest,
                    DEFAULT_COMPOSE_PROJECT,
                    compose_file=state.compose_file,
                )
                release.compose.require_local_docker()
                release.require_healthy()
                print("Active release is healthy; no application restart.")
                return
            attempt = selected.retained or state.prepare(
                selected.settings, installed.compose_yaml, rollback=rollback
            )
            release = BetaRelease.from_manifest(
                attempt.manifest,
                DEFAULT_COMPOSE_PROJECT,
                compose_file=attempt.compose_file,
            )
            release.compose.require_local_docker()
            release.compose.run("config", "--quiet")
            release.compose.run("pull")
            state.begin_activation(attempt)
            release.activate(rollback=attempt.rollback)
            release.require_healthy()
            state.promote(state.mark_activated(attempt))
            print(f"Activated {installed.release.images.source_commit}")
