"""Provision and quarantine an isolated restore project without application startup."""

import subprocess

from api.deployment.services import POSTGRES_SERVICE, REDIS_SERVICE, DeploymentService
from api.lifecycle.commands import LIFECYCLE_MODULE, DataCommand

from scripts.beta_backup.policy import BACKUP_PROCESS_TIMEOUT_SECONDS
from scripts.beta_release import REPOSITORY, BetaRelease


class RestoreDestination:
    def __init__(self, release: BetaRelease) -> None:
        self._release = release

    def prepare(self) -> None:
        existing = subprocess.check_output(
            self._release.command("ps", "--all", "--quiet"),
            env=self._release.environment,
            cwd=REPOSITORY,
            timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
        )
        if existing.strip():
            raise ValueError("restore destination must be a new isolated project")
        self._release.compose(
            "up", "-d", "--wait", "--no-deps", POSTGRES_SERVICE, REDIS_SERVICE
        )

    def quarantine(self) -> None:
        self._release.compose(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            DeploymentService.RECOVERY,
            "-m",
            LIFECYCLE_MODULE,
            DataCommand.QUARANTINE_RESTORE,
        )
