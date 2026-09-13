"""Create and publish the active release's encrypted recovery point."""

from pathlib import Path

from scripts.beta_backup.archives import BackupArchives
from scripts.beta_backup.backup import BetaBackup
from scripts.beta_backup.database import ComposeDatabase
from scripts.beta_backup.remote import RemoteBackups
from scripts.beta_release import BetaRelease
from scripts.deployment.bundle import ReleaseBundle


class BackupWorkflow:
    def __init__(
        self,
        release: BetaRelease,
        remote: RemoteBackups,
        recipients: Path,
        staging: Path,
    ) -> None:
        self.release = release
        self.remote = remote
        self.recipients = recipients
        self.staging = staging

    def create(self, bundle_archive_path: Path) -> Path:
        source_commit = self.release.settings.images.source_commit
        ReleaseBundle.from_archive(bundle_archive_path, commit=source_commit)
        archives = BackupArchives(self.staging)
        try:
            archive = BetaBackup(
                ComposeDatabase(self.release.compose), self.staging, self.recipients
            ).create()
            self.remote.upload(
                archive, bundle_archive_path, source_commit=source_commit
            )
            return archive
        finally:
            archives.prune_staging()
