"""Private data-maintenance command vocabulary."""

from enum import StrEnum


class DataCommand(StrEnum):
    CLEAN = "clean"
    QUARANTINE_RESTORE = "quarantine-restore"
    APPROVE_RESTORED_ACCOUNT = "approve-restored-account"


LIFECYCLE_MODULE = "api.lifecycle"
RESTORE_RECONCILIATION_FLAG = "--reconciled-against-current-records"
