"""Persisted data-lifecycle column contracts."""

from enum import StrEnum


class DeletionColumn(StrEnum):
    USER_ID = "user_id"
    REQUESTED_AT = "requested_at"
    COMPLETED_AT = "completed_at"


HISTORY_EXPIRED_AT_COLUMN = "history_expired_at"
RESTORE_QUARANTINED_AT_COLUMN = "restore_quarantined_at"

DELETION_REQUESTS_TABLE = "account_deletion_requests"
DELETION_REQUEST_TIME_INDEX = "ix_account_deletion_requests_requested_at"
