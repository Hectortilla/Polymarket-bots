"""Canonical encrypted local staging; remote verification owns recovery points."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from api.lifecycle.policy import BACKUP_INTERVAL_HOURS
from polybot.persistence.hashing import sha256_file

from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.paths import PrivateBackupPath
from scripts.beta_backup.policy import (
    MAX_RETAINED_STAGING_ARCHIVES,
    backup_retention_cutoff,
)


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
        cutoff = backup_retention_cutoff()
        for path, archive in self._completed():
            if archive.snapshot_started_at <= cutoff:
                path.unlink()

    def prune_staging(self) -> None:
        archives = sorted(
            self._completed(),
            key=lambda item: item[1].snapshot_started_at,
            reverse=True,
        )
        for path, _ in archives[MAX_RETAINED_STAGING_ARCHIVES:]:
            path.unlink()
        cutoff = (
            datetime.now(UTC) - timedelta(hours=BACKUP_INTERVAL_HOURS)
        ).timestamp()
        for path in self.directory.glob(".incomplete-*"):
            if (
                not path.is_symlink()
                and path.is_file()
                and path.stat().st_mtime < cutoff
            ):
                path.unlink()

    def _completed(self):
        for path in self.directory.iterdir():
            archive = ArchiveName.parse(path.name)
            if archive is not None and not path.is_symlink() and path.is_file():
                yield path, archive
