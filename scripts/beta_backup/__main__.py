"""Private host backup and isolated restoration commands."""

import argparse
import subprocess
import tarfile
from pathlib import Path
from typing import assert_never

from scripts.beta_backup.commands import BackupCommand
from scripts.beta_backup.download import RecoveryDownload
from scripts.beta_backup.remote import RemoteBackups
from scripts.beta_backup.restore import BetaRestore
from scripts.beta_backup.workflow import BackupWorkflow
from scripts.beta_release import BetaRelease
from scripts.compose_project import DEFAULT_COMPOSE_PROJECT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser(BackupCommand.CREATE)
    backup.add_argument("manifest", type=Path)
    backup.add_argument("--project", default=DEFAULT_COMPOSE_PROJECT)
    backup.add_argument("--directory", type=Path, required=True)
    backup.add_argument("--recipients", type=Path, required=True)
    backup.add_argument("--config", type=Path, required=True)
    backup.add_argument("--remote", required=True)
    backup.add_argument("--bundle", type=Path, required=True)
    check = commands.add_parser(BackupCommand.CHECK)
    check.add_argument("--directory", type=Path, required=True)
    check.add_argument("--config", type=Path, required=True)
    check.add_argument("--remote", required=True)
    download = commands.add_parser(BackupCommand.DOWNLOAD)
    download.add_argument("archive")
    download.add_argument("--directory", type=Path, required=True)
    download.add_argument("--config", type=Path, required=True)
    download.add_argument("--remote", required=True)
    restore = commands.add_parser(BackupCommand.RESTORE)
    restore.add_argument("manifest", type=Path)
    restore.add_argument("archive", type=Path)
    restore.add_argument("--identity", type=Path, required=True)
    restore.add_argument("--scratch-directory", type=Path, required=True)
    args = parser.parse_args()
    command = BackupCommand(args.command)
    try:
        if command == BackupCommand.DOWNLOAD:
            archive, destination = RecoveryDownload(
                RemoteBackups(args.config, args.remote, args.directory)
            ).prepare(args.archive, args.directory)
            print(
                f"Verified {archive.name}; matching source prepared in {destination}. Supply isolated runtime secrets before restore."
            )
        elif command == BackupCommand.CHECK:
            RemoteBackups(args.config, args.remote, args.directory).require_recent()
            print("Backup recovery-point target is satisfied.")
        elif command == BackupCommand.CREATE:
            archive = BackupWorkflow(
                BetaRelease.from_manifest(args.manifest, args.project),
                RemoteBackups(args.config, args.remote, args.directory),
                args.recipients,
                args.directory,
            ).create(args.bundle)
            print(f"Off-server backup verified: {archive.name}")
        elif command is BackupCommand.RESTORE:
            project, elapsed_seconds = BetaRestore(
                args.manifest, args.archive, args.identity, args.scratch_directory
            ).restore()
            print(
                f"Restore quarantined in {project}; elapsed {elapsed_seconds:.1f} seconds. No application processes started."
            )
        else:
            assert_never(command)
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ):
        parser.exit(
            1,
            "Backup/restore failed. Keep restoration closed; inspect private dependencies and permissions. No successful completion is claimed.\n",
        )


if __name__ == "__main__":
    main()
