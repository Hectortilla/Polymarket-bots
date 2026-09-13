"""Canonical archive/release-bundle pairs retained on remote storage."""

import re
from dataclasses import dataclass

from scripts.beta_backup.archive_name import ARCHIVE_CHECKSUM_HEX_LENGTH, ArchiveName
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME


@dataclass(frozen=True)
class ReleaseBundleName:
    archive: ArchiveName
    checksum: str

    def format(self) -> str:
        return f"{self.archive.format()}.{self.checksum}.{RELEASE_BUNDLE_FILENAME}"

    @classmethod
    def parse(cls, name: str) -> "ReleaseBundleName | None":
        suffix = "." + RELEASE_BUNDLE_FILENAME
        if not name.endswith(suffix):
            return None
        archive_text, separator, checksum = name.removesuffix(suffix).rpartition(".")
        archive = ArchiveName.parse(archive_text)
        if (
            not separator
            or archive is None
            or re.fullmatch(rf"[a-f0-9]{{{ARCHIVE_CHECKSUM_HEX_LENGTH}}}", checksum)
            is None
        ):
            return None
        return cls(archive, checksum)


@dataclass(frozen=True)
class RemoteBackupPair:
    archive: ArchiveName
    bundle: ReleaseBundleName

    @property
    def archive_filename(self) -> str:
        return self.archive.format()

    @property
    def bundle_filename(self) -> str:
        return self.bundle.format()


def artifact_snapshot(name: str) -> ArchiveName | None:
    # Atomic rclone uploads may leave fingerprinted partials after process loss.
    completed_name = re.sub(r"\.[a-z0-9]{1,64}\.partial$", "", name)
    bundle = ReleaseBundleName.parse(completed_name)
    return bundle.archive if bundle else ArchiveName.parse(completed_name)
