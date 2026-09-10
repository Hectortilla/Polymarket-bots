"""Use the pinned PostgreSQL container's own dump and restore utilities."""

import subprocess

from api.deployment.services import POSTGRES_SERVICE

from scripts.beta_backup.policy import BACKUP_PROCESS_TIMEOUT_SECONDS
from scripts.beta_release import REPOSITORY, BetaRelease

POSTGRES_USER = "polybot"
POSTGRES_DATABASE = "polybot"


class ComposeDatabase:
    def __init__(self, release: BetaRelease) -> None:
        release.require_local_docker()
        self.release = release

    def restore(self, source) -> None:
        subprocess.run(
            self.release.command(
                "exec",
                "-T",
                POSTGRES_SERVICE,
                "pg_restore",
                "--username",
                POSTGRES_USER,
                "--dbname",
                POSTGRES_DATABASE,
                "--no-owner",
                "--no-acl",
                "--single-transaction",
                "--exit-on-error",
            ),
            stdin=source,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
            env=self.release.environment,
            cwd=REPOSITORY,
        )

    def dump_command(self) -> list[str]:
        return self.release.command(
            "exec",
            "-T",
            POSTGRES_SERVICE,
            "pg_dump",
            "--username",
            POSTGRES_USER,
            "--dbname",
            POSTGRES_DATABASE,
            "--format=custom",
            "--no-owner",
            "--no-acl",
        )
