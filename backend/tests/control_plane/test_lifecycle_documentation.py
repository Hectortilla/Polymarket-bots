"""Lifecycle disclosures, CLI vocabulary and scheduler budgets track their owners."""

from pathlib import Path

from api.http.protocol import IDEMPOTENCY_RECOVERY_HEADER
from api.lifecycle import policy
from api.lifecycle.commands import (
    LIFECYCLE_MODULE,
    RESTORE_RECONCILIATION_FLAG,
    DataCommand,
)
from api.lifecycle.http import ACCOUNT_DELETION_PATH
from api.limits.policy import PAPER_BETA
from fastapi import status

from scripts.beta_backup.archive_name import ARCHIVE_CHECKSUM_ALGORITHM
from scripts.beta_backup.commands import BackupCommand
from scripts.beta_backup.policy import (
    BACKUP_PROCESS_TIMEOUT_SECONDS,
    BACKUP_SERVICE_TIMEOUT_SECONDS,
)

RUNBOOK = Path("docs/beta-data-lifecycle.md")


def lifecycle_policy_table():
    entries = {
        "Backup interval hours": policy.BACKUP_INTERVAL_HOURS,
        "Backup retention days": policy.BACKUP_RETENTION_DAYS,
        "Recovery-point target hours": policy.RECOVERY_POINT_HOURS,
        "Isolated restore target hours": policy.RECOVERY_TIME_HOURS,
        "Retained terminal runs per account": PAPER_BETA.retained_runs,
        "Terminal history retention days": PAPER_BETA.history_retention_days,
        "Deletion target hours": policy.DELETION_TARGET_HOURS,
        "Completed receipt / audit retention days": policy.OPERATOR_AUDIT_RETENTION_DAYS,
        "Maintenance interval seconds": policy.CLEANUP_INTERVAL_SECONDS,
        "History / per-account purge run batch": policy.CLEANUP_RUN_BATCH_SIZE,
        "Event deletion batch per selected run": policy.CLEANUP_EVENT_BATCH_SIZE,
        "Account deletion batch": policy.CLEANUP_ACCOUNT_BATCH_SIZE,
        "Audit / completed receipt batch": policy.CLEANUP_AUDIT_BATCH_SIZE,
        "Deletion quiescence seconds": policy.DELETION_QUIESCENCE_SECONDS,
    }
    return "\n".join(
        [
            "| Policy | Value |",
            "| --- | ---: |",
            *(f"| {name} | {value} |" for name, value in entries.items()),
        ]
    )


def lifecycle_policy_summary():
    return (
        f"Approved beta policy: encrypted backups every {policy.BACKUP_INTERVAL_HOURS} hours, retained {policy.BACKUP_RETENTION_DAYS} days; "
        f"recovery point ≤{policy.RECOVERY_POINT_HOURS} hours and isolated restore ≤{policy.RECOVERY_TIME_HOURS} hours; "
        f"up to {PAPER_BETA.retained_runs} terminal runs per account for {PAPER_BETA.history_retention_days} days; "
        f"immediate deletion quiescence and eligible erasure within {policy.DELETION_TARGET_HOURS} hours; "
        f"minimal completed deletion receipts and operator audits retained {policy.OPERATOR_AUDIT_RETENTION_DAYS} days."
    )


def test_lifecycle_disclosures_and_commands_match_policy():
    runbook = RUNBOOK.read_text()
    assert lifecycle_policy_table() in runbook
    assert f"`{ARCHIVE_CHECKSUM_ALGORITHM}` digest" in runbook
    for path in (
        RUNBOOK,
        Path("docs/web-control-plane-spec.md"),
        Path("docs/implementation-plan.md"),
    ):
        assert lifecycle_policy_summary() in path.read_text()
    for path in (RUNBOOK, Path("docs/web-control-plane-architecture.md")):
        text = path.read_text()
        assert IDEMPOTENCY_RECOVERY_HEADER in text
        assert (
            f"returns {status.HTTP_410_GONE}" in text
            or f"return {status.HTTP_410_GONE}" in text
        )
    for command in DataCommand:
        assert f"python -m {LIFECYCLE_MODULE} {command}" in runbook
    for command in BackupCommand:
        assert f"python -m scripts.beta_backup {command}" in runbook
    assert RESTORE_RECONCILIATION_FLAG in runbook
    architecture = Path("docs/web-control-plane-architecture.md").read_text()
    route_line = next(
        line
        for line in architecture.splitlines()
        if line.startswith(f"- `POST {ACCOUNT_DELETION_PATH}`")
    )
    assert f"return {status.HTTP_202_ACCEPTED}" in route_line


def test_backup_units_match_cadence_timeout_and_require_mounted_storage():
    directory = Path("deploy/systemd")
    timer = (directory / "polybot-backup.timer").read_text()
    assert policy.BACKUP_INTERVAL_HOURS == 24
    assert "OnCalendar=*-*-* 02:00:00 UTC" in timer
    assert "Persistent=true" in timer
    backup = (directory / "polybot-backup.service").read_text()
    assert f"TimeoutStartSec={BACKUP_SERVICE_TIMEOUT_SECONDS}" in backup
    assert BACKUP_SERVICE_TIMEOUT_SECONDS > BACKUP_PROCESS_TIMEOUT_SECONDS * 2
    for filename in ("polybot-backup.service", "polybot-backup-check.service"):
        assert (
            "AssertPathIsMountPoint=/mnt/polybot-backups"
            in (directory / filename).read_text()
        )
