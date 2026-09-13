"""Canonical encrypted local staging; remote verification owns recovery points."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from api.lifecycle.policy import BACKUP_RETENTION_DAYS
from polybot.persistence.hashing import sha256_file

from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.paths import PrivateBackupPath


class BackupArchives:
    def __init__(self, directory: Path) -> None:
        self.directory = PrivateBackupPath.directory(directory)

    def publish(self, source: Path, snapshot_started_at: datetime) -> Path:
        destination = (
            self.directory
            / ArchiveName(snapshot_started_at, uuid4(), sha256_file(source)).format()
        )
        os.replace(source, destination)
        directory_fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination

    def expire(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=BACKUP_RETENTION_DAYS)
        for path, archive in self._completed():
            if archive.snapshot_started_at <= cutoff:
                path.unlink()

    def _completed(self):
        for path in self.directory.iterdir():
            archive = ArchiveName.parse(path.name)
            if archive is not None and not path.is_symlink() and path.is_file():
                yield path, archive
