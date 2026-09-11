"""Provision and quarantine an isolated restore project without application startup."""

import subprocess

from api.deployment.services import POSTGRES_SERVICE, REDIS_SERVICE, DeploymentService
from api.lifecycle.commands import LIFECYCLE_MODULE, DataCommand

from scripts.beta_backup.policy import BACKUP_PROCESS_TIMEOUT_SECONDS
from scripts.compose_project import REPOSITORY, ComposeProject


class RestoreDestination:
    def __init__(self, project: ComposeProject) -> None:
        self._project = project

    def prepare(self) -> None:
        existing = subprocess.check_output(
            self._project.command("ps", "--all", "--quiet"),
            env=self._project.environment,
            cwd=REPOSITORY,
            timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
        )
        if existing.strip():
            raise ValueError("restore destination must be a new isolated project")
        self._project.run(
            "up", "-d", "--wait", "--no-deps", POSTGRES_SERVICE, REDIS_SERVICE
        )

    def quarantine(self) -> None:
        self._project.run(
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
