"""Verified off-server recovery points through the official rclone SFTP tool."""

import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from api.lifecycle.policy import RECOVERY_POINT_HOURS
from polybot.persistence.hashing import sha256_file

from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.paths import PrivateBackupPath
from scripts.beta_backup.remote.artifacts import ReleaseBundleName
from scripts.beta_backup.remote.config import SftpRemoteConfig
from scripts.beta_backup.remote.inventory import RemoteBackupInventory
from scripts.beta_backup.remote.transport import RcloneSftp, RemoteBackupError
from scripts.deployment.bundle import ReleaseBundle
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.private_files import PRIVATE_FILE_MODE


class RemoteBackups:
    def __init__(self, config: Path, remote: str, staging: Path) -> None:
        self.transport = RcloneSftp(SftpRemoteConfig.read(config, remote, staging))
        self.inventory = RemoteBackupInventory(self.transport)

    def upload(
        self, encrypted_archive: Path, release_bundle: Path, *, source_commit: str
    ) -> None:
        archive_name = ArchiveName.parse(encrypted_archive.name)
        if (
            archive_name is None
            or sha256_file(encrypted_archive) != archive_name.checksum
        ):
            raise ValueError("invalid encrypted archive checksum")
        ReleaseBundle.from_archive(release_bundle, commit=source_commit)
        bundle_name = ReleaseBundleName(archive_name, sha256_file(release_bundle))
        # Publish the encrypted_archive last; recovery needs both verified pair members.
        self.transport.run(
            "copyto",
            str(release_bundle),
            self.transport.remote_artifact_path(bundle_name.format()),
            "--immutable",
        )
        if self.transport.checksum(bundle_name.format()) != bundle_name.checksum:
            raise RemoteBackupError("remote release bundle checksum mismatch")
        self.transport.run(
            "copyto",
            str(encrypted_archive),
            self.transport.remote_artifact_path(encrypted_archive.name),
            "--immutable",
        )
        if self.transport.checksum(encrypted_archive.name) != archive_name.checksum:
            raise RemoteBackupError("remote encrypted archive checksum mismatch")
        encrypted_archive.unlink()
        self.inventory.expire()

    def require_recent(self) -> None:
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=RECOVERY_POINT_HOURS)
        for pair in sorted(
            self.inventory.completed_pairs(),
            key=lambda item: item.archive.snapshot_started_at,
            reverse=True,
        ):
            if (
                cutoff <= pair.archive.snapshot_started_at <= now
                and self.inventory.is_intact(pair)
            ):
                return
        raise RemoteBackupError("no verified off-server recovery point within policy")

    def download(
        self, archive_filename: str, staging_directory: Path
    ) -> tuple[Path, Path]:
        directory = PrivateBackupPath.directory(staging_directory)
        matches = [
            pair
            for pair in self.inventory.completed_pairs()
            if pair.archive_filename == archive_filename
        ]
        if len(matches) != 1:
            raise ValueError("archive and matching release bundle are required")
        pair = matches[0]
        archive, bundle = (
            directory / archive_filename,
            directory / RELEASE_BUNDLE_FILENAME,
        )
        if any(path.exists() or path.is_symlink() for path in (archive, bundle)):
            raise ValueError("download destination must not contain these artifacts")
        try:
            self.transport.run(
                "copyto",
                self.transport.remote_artifact_path(archive_filename),
                str(archive),
            )
            self.transport.run(
                "copyto",
                self.transport.remote_artifact_path(pair.bundle_filename),
                str(bundle),
            )
            archive.chmod(PRIVATE_FILE_MODE)
            bundle.chmod(PRIVATE_FILE_MODE)
            if (
                sha256_file(archive) != pair.archive.checksum
                or sha256_file(bundle) != pair.bundle.checksum
            ):
                raise RemoteBackupError("download checksum mismatch")
            ReleaseBundle.from_archive(bundle)
        except (OSError, ValueError, RuntimeError, tarfile.TarError):
            archive.unlink(missing_ok=True)
            bundle.unlink(missing_ok=True)
            raise
        return archive, bundle
