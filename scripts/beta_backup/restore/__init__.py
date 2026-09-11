"""Authenticated restoration is isolated and closed until explicit reconciliation."""

from pathlib import Path
from time import monotonic
from uuid import uuid4

from api.lifecycle.policy import RECOVERY_TIME_HOURS

from scripts.beta_backup.database import ComposeDatabase
from scripts.beta_backup.restore.decrypt import DecryptedArchive
from scripts.beta_backup.restore.destination import RestoreDestination
from scripts.beta_release import BetaRelease

RESTORE_PROJECT_PREFIX = "polybot-restore-"


class BetaRestore:
    def __init__(
        self, manifest: Path, archive: Path, identity: Path, scratch_directory: Path
    ) -> None:
        self.manifest = manifest
        self._archive = DecryptedArchive(archive, identity, scratch_directory)
        self.project = RESTORE_PROJECT_PREFIX + uuid4().hex

    def restore(self) -> tuple[str, float]:
        started_at_monotonic = monotonic()
        release = BetaRelease(self.manifest, self.project)
        database = ComposeDatabase(release.compose)
        destination = RestoreDestination(release.compose)
        with self._archive.open() as plaintext:
            destination.prepare()
            database.restore(plaintext)
        destination.quarantine()
        elapsed_seconds = monotonic() - started_at_monotonic
        if elapsed_seconds > RECOVERY_TIME_HOURS * 3600:
            raise RuntimeError(
                "isolated restore exceeded the recovery target; keep deployment closed"
            )
        return self.project, elapsed_seconds
