"""Publish an encrypted database snapshot only after the complete pipeline succeeds."""

from datetime import datetime, timezone
from pathlib import Path

from scripts.beta_backup.archives import BackupArchives
from scripts.beta_backup.backup.pipeline import EncryptedDump
from scripts.beta_backup.database import ComposeDatabase


class BetaBackup:
    def __init__(
        self, database: ComposeDatabase, directory: Path, recipients: Path
    ) -> None:
        self.archives = BackupArchives(directory)
        self._dump = EncryptedDump(database, self.archives.directory, recipients)

    def create(self) -> Path:
        self.archives.expire()
        snapshot_started_at = datetime.now(timezone.utc)
        with self._dump.stage() as temporary_archive_path:
            return self.archives.publish(temporary_archive_path, snapshot_started_at)
