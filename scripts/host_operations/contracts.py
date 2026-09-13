"""Host command and stable diagnostic vocabulary."""

from enum import StrEnum

from scripts.deployment.units import (
    BACKUP_CHECK_SERVICE_UNIT,
    BACKUP_CHECK_TIMER_UNIT,
    BACKUP_SERVICE_UNIT,
    BACKUP_TIMER_UNIT,
    MONITOR_SERVICE_UNIT,
    MONITOR_TIMER_UNIT,
)


class HostOperation(StrEnum):
    BACKUP = "backup"
    BACKUP_CHECK = "backup-check"
    MONITOR = "monitor"
    STATUS = "status"


class HostCheckCode(StrEnum):
    APPLICATION = "application"
    HOST_SERVICES = "host_services"
    HTTPS_CERTIFICATE = "https_certificate"
    BACKUP_FRESHNESS = "backup_freshness"
    BACKUP = "backup"
    BACKUP_CHECK = "backup-check"


REQUIRED_ACTIVE_UNITS = (
    "docker",
    "tailscaled",
    BACKUP_TIMER_UNIT,
    BACKUP_CHECK_TIMER_UNIT,
    MONITOR_TIMER_UNIT,
)
REQUIRED_COMPLETED_UNITS = (
    BACKUP_SERVICE_UNIT,
    BACKUP_CHECK_SERVICE_UNIT,
    MONITOR_SERVICE_UNIT,
)
