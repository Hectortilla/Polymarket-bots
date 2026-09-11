"""Private host backup and isolated restoration commands."""

import argparse
from pathlib import Path

from scripts.beta_backup.archives import BackupArchives
from scripts.beta_backup.backup import BetaBackup
from scripts.beta_backup.commands import BackupCommand
from scripts.beta_backup.database import ComposeDatabase
from scripts.beta_backup.restore import BetaRestore
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
    check = commands.add_parser(BackupCommand.CHECK)
    check.add_argument("--directory", type=Path, required=True)
    restore = commands.add_parser(BackupCommand.RESTORE)
    restore.add_argument("manifest", type=Path)
    restore.add_argument("archive", type=Path)
    restore.add_argument("--identity", type=Path, required=True)
    restore.add_argument("--scratch-directory", type=Path, required=True)
    args = parser.parse_args()
    command = BackupCommand(args.command)
    try:
        if command is BackupCommand.CHECK:
            BackupArchives(args.directory).require_recent()
            print("Backup recovery-point target is satisfied.")
        elif command is BackupCommand.CREATE:
            archive = BetaBackup(
                ComposeDatabase(BetaRelease(args.manifest, args.project).compose),
                args.directory,
                args.recipients,
            ).create()
            print(f"Encrypted backup complete: {archive.name}")
        else:
            project, elapsed_seconds = BetaRestore(
                args.manifest, args.archive, args.identity, args.scratch_directory
            ).restore()
            print(
                f"Restore quarantined in {project}; elapsed {elapsed_seconds:.1f} seconds. No application processes started."
            )
    except Exception:
        parser.exit(
            1,
            "Backup/restore failed. Keep restoration closed; inspect private dependencies and permissions. No successful completion is claimed.\n",
        )


if __name__ == "__main__":
    main()
