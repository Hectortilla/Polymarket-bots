"""Prepare matching verified recovery sources without leaving partial extraction."""

import shutil
import tarfile
from pathlib import Path

from scripts.beta_backup.remote import RemoteBackups


class RecoveryDownload:
    def __init__(self, remote: RemoteBackups) -> None:
        self.remote = remote

    def prepare(
        self, archive_filename: str, staging_directory: Path
    ) -> tuple[Path, Path]:
        release_directory = staging_directory / "release"
        if release_directory.exists() or release_directory.is_symlink():
            raise ValueError("recovery release directory must not exist")
        archive, bundle = self.remote.download(archive_filename, staging_directory)
        try:
            release_directory.mkdir(mode=0o700)
            with tarfile.open(bundle) as source:
                source.extractall(release_directory, filter="data")
        except (OSError, ValueError, tarfile.TarError):
            shutil.rmtree(release_directory, ignore_errors=True)
            archive.unlink(missing_ok=True)
            bundle.unlink(missing_ok=True)
            raise
        return archive, release_directory
