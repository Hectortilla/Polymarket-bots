"""Remote archive pairing, retention selection and integrity evidence."""

from collections import defaultdict

from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.policy import backup_retention_cutoff
from scripts.beta_backup.remote.artifacts import (
    ReleaseBundleName,
    RemoteBackupPair,
    artifact_snapshot,
)
from scripts.beta_backup.remote.transport import RcloneSftp


class RemoteBackupInventory:
    def __init__(self, transport: RcloneSftp) -> None:
        self.transport = transport

    def completed_pairs(self) -> tuple[RemoteBackupPair, ...]:
        archives = []
        bundles = defaultdict(list)
        for entry in self.transport.list_entries():
            if entry.is_dir:
                continue
            archive = ArchiveName.parse(entry.name)
            if archive:
                archives.append(archive)
            bundle = ReleaseBundleName.parse(entry.name)
            if bundle:
                bundles[bundle.archive.format()].append(bundle)
        return tuple(
            RemoteBackupPair(archive, bundles[archive.format()][0])
            for archive in archives
            if len(bundles[archive.format()]) == 1
        )

    def is_intact(self, pair: RemoteBackupPair) -> bool:
        return (
            self.transport.checksum(pair.archive_filename) == pair.archive.checksum
            and self.transport.checksum(pair.bundle_filename) == pair.bundle.checksum
        )

    def expire(self) -> None:
        cutoff = backup_retention_cutoff()
        for entry in self.transport.list_entries():
            archive = artifact_snapshot(entry.name)
            if not entry.is_dir and archive and archive.snapshot_started_at <= cutoff:
                self.transport.run(
                    "deletefile", self.transport.remote_artifact_path(entry.name)
                )
