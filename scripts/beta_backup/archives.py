"""Only completed, checksum-valid archives can satisfy the backup recovery point."""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from api.lifecycle.policy import BACKUP_RETENTION_DAYS, RECOVERY_POINT_HOURS

from scripts.beta_backup.archive_name import ARCHIVE_CHECKSUM_ALGORITHM, ArchiveName
from scripts.beta_backup.paths import PrivateBackupPath


class BackupArchives:
    def __init__(self, directory: Path) -> None:
        self.directory = PrivateBackupPath.directory(directory)

    def publish(self, source: Path, snapshot_started_at: datetime) -> Path:
        destination = (
            self.directory
            / ArchiveName(snapshot_started_at, uuid4(), self.checksum(source)).format()
        )
        os.replace(source, destination)
        directory_fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination

    def expire(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=BACKUP_RETENTION_DAYS)
        for path, archive in self._completed():
            if archive.snapshot_started_at <= cutoff:
                path.unlink()

    def require_recent(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=RECOVERY_POINT_HOURS)
        for path, archive in sorted(
            self._completed(),
            key=lambda item: item[1].snapshot_started_at,
            reverse=True,
        ):
            if (
                cutoff <= archive.snapshot_started_at <= now
                and self.checksum(path) == archive.checksum
            ):
                return
        raise RuntimeError(
            "no intact completed backup within the recovery-point target"
        )

    @staticmethod
    def checksum(path: Path) -> str:
        with path.open("rb") as archive:
            return hashlib.file_digest(archive, ARCHIVE_CHECKSUM_ALGORITHM).hexdigest()

    def _completed(self):
        for path in self.directory.iterdir():
            archive = ArchiveName.parse(path.name)
            if archive is not None and not path.is_symlink() and path.is_file():
                yield path, archive
