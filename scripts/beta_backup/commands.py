"""Private backup command vocabulary."""

from enum import StrEnum


class BackupCommand(StrEnum):
    CREATE = "create"
    CHECK = "check"
    RESTORE = "restore"
