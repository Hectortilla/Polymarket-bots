"""Host backup/restore process budgets and encryption tool."""

from datetime import UTC, datetime, timedelta

from api.lifecycle.policy import BACKUP_INTERVAL_HOURS, BACKUP_RETENTION_DAYS

BACKUP_PROCESS_TIMEOUT_SECONDS = 1800
BACKUP_SERVICE_TIMEOUT_SECONDS = 3700
AGE_BINARY = "age"
MAX_RETAINED_STAGING_ARCHIVES = 2
# Preserve backup protection for existing inventories that omit the opt-out.
DEFAULT_BACKUPS_ENABLED = True


def backup_retention_cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(days=BACKUP_RETENTION_DAYS)


def backup_calendar() -> str:
    interval = _validated_calendar_interval(BACKUP_INTERVAL_HOURS)
    return "daily" if interval == 24 else f"*-*-* 0/{interval}:00:00"


def _validated_calendar_interval(interval: int) -> int:
    if not 0 < interval <= 24 or 24 % interval:
        raise ValueError(
            "backup interval has no supported daily calendar representation"
        )
    return interval
