"""Export deployment-owner contracts across the Ansible template boundary."""

from typing import TypedDict

from api.auth.config import AUTH_ORIGIN_ENV
from api.auth.mail.config import (
    SMTP_FROM_ENV,
    SMTP_HOST_ENV,
    SMTP_PORT_ENV,
    SMTP_SECURITY_ENV,
)
from api.deployment.settings import (
    DEFAULT_WORKER_DATABASE_POOL_SIZE,
    LIVE_REDIS_SHARDS_ENV,
    WORKER_DATABASE_POOL_SIZE_ENV,
)
from api.http.routes.paths import HEALTH_PATH, api_route_path
from polybot.persistence.hashing import SHA256_ALGORITHM

from scripts.beta_backup.policy import BACKUP_SERVICE_TIMEOUT_SECONDS, backup_calendar
from scripts.beta_backup.remote.config import BACKUP_REMOTE_NAME, SFTP_BACKEND
from scripts.deployment.attempt import ACTIVATION_TIMEOUT_SECONDS
from scripts.deployment.bundle.contracts import RELEASE_BUNDLE_FILENAME
from scripts.deployment.ingress import IngressMode
from scripts.deployment.inventory import SUPPORTED_ARCHITECTURES
from scripts.deployment.network import HEALTH_HTTP_STATUS
from scripts.deployment.paths import (
    CLOUDFLARE_CONFIGURATION_DIRECTORY,
    CURRENT_RELEASE_NAME,
    MANIFEST_NAME,
    OPERATIONS_CONFIGURATION_NAME,
    REGISTRY_AUTH_DIRECTORY_NAME,
    RELEASES_DIRECTORY_NAME,
    RUNTIME_CONFIGURATION_NAME,
    SECRETS_DIRECTORY_NAME,
    STAGING_DIRECTORY_NAME,
)
from scripts.deployment.runtime_contracts import HTTP_PORT_ENV, SECRETS_DIRECTORY_ENV
from scripts.deployment.ssh_access import (
    DEPLOYMENT_SSH_USER,
    SSH_HARDENING_POLICY,
    SSHD_HARDENING_PATH,
    SSHD_MAIN_PATH,
)
from scripts.deployment.storage import SecretFile
from scripts.deployment.tailscale import PRIVATE_HTTPS_PORT, TAILNET_HOST_TAG
from scripts.deployment.toolchain import UV_VERSION
from scripts.deployment.transport_files import HostTransportFile
from scripts.deployment.units import (
    ACTIVATION_SERVICE_UNIT,
    BACKUP_CHECK_SERVICE_UNIT,
    BACKUP_SERVICE_UNIT,
    CLOUDFLARE_SERVICE_UNIT,
    CLOUDFLARE_SERVICE_USER,
    MONITOR_SERVICE_UNIT,
)
from scripts.host_operations.contracts import (
    BACKUP_SERVICE_UNITS,
    BACKUP_TIMER_UNITS,
    REQUIRED_ACTIVE_UNITS,
    REQUIRED_COMPLETED_UNITS,
    HostOperation,
)
from scripts.host_operations.policy import (
    BACKUP_CHECK_CALENDAR,
    HTTPS_PROBE_TIMEOUT_SECONDS,
    MONITOR_CALENDAR,
)


class RuntimeKeys(TypedDict):
    live_redis_shards: str
    worker_database_pool_size: str
    origin: str
    http_port: str
    secrets: str
    smtp_host: str
    smtp_port: str
    smtp_security: str
    smtp_from: str


class SecretFileNames(TypedDict):
    database_url: str
    postgres_password: str
    redis_url: str
    smtp_username: str
    smtp_password: str


class TransportFileNames(TypedDict):
    cloudflare_token: str
    sftp_key: str
    sftp_known_hosts: str
    age_recipients: str
    rclone_config: str
    smtp_config: str


class HostPaths(TypedDict):
    cloudflare: str
    active_manifest: str
    registry: str
    current: str
    releases: str
    runtime: str
    operations: str
    staging: str
    secrets: str
    bundle: str


class HostOperationNames(TypedDict):
    backup: str
    backup_check: str
    monitor: str
    status: str


class ServiceUnitNames(TypedDict):
    cloudflare: str
    activation: str
    backup: str
    backup_check: str
    monitor: str


class DeploymentContract(TypedDict):
    worker_database_pool_size: int
    cloudflare_user: str
    ingress_modes: dict[str, str]
    ssh_user: str
    ssh_policy: dict[str, str]
    sshd_main: str
    sshd_hardening: str
    https_probe_timeout: int
    architecture_names: dict[str, str]
    activation_poll_interval: int
    activation_poll_retries: int
    backup_check_calendar: str
    monitor_calendar: str
    service_units: ServiceUnitNames
    checksum_algorithm: str
    calendar: str
    timeout: int
    health_path: str
    health_status: int
    https_port: int
    host_tag: str
    uv_version: str
    activation_timeout: int
    runtime_keys: RuntimeKeys
    secret_files: SecretFileNames
    transport_files: TransportFileNames
    backup_remote: str
    sftp_backend: str
    paths: HostPaths
    operations: HostOperationNames
    backup_timers: list[str]
    backup_services: list[str]
    timers: list[str]
    services: list[str]


def deployment_contract() -> DeploymentContract:
    return {
        "worker_database_pool_size": DEFAULT_WORKER_DATABASE_POOL_SIZE,
        "cloudflare_user": CLOUDFLARE_SERVICE_USER,
        "ingress_modes": {mode.name.lower(): mode.value for mode in IngressMode},
        "ssh_user": DEPLOYMENT_SSH_USER,
        "ssh_policy": SSH_HARDENING_POLICY,
        "sshd_main": SSHD_MAIN_PATH,
        "sshd_hardening": SSHD_HARDENING_PATH,
        "backup_check_calendar": BACKUP_CHECK_CALENDAR,
        "monitor_calendar": MONITOR_CALENDAR,
        "https_probe_timeout": HTTPS_PROBE_TIMEOUT_SECONDS,
        "architecture_names": SUPPORTED_ARCHITECTURES,
        "activation_poll_interval": 5,
        "activation_poll_retries": ACTIVATION_TIMEOUT_SECONDS // 5 + 2,
        "checksum_algorithm": SHA256_ALGORITHM,
        "service_units": {
            "cloudflare": CLOUDFLARE_SERVICE_UNIT,
            "activation": ACTIVATION_SERVICE_UNIT,
            "backup": BACKUP_SERVICE_UNIT,
            "backup_check": BACKUP_CHECK_SERVICE_UNIT,
            "monitor": MONITOR_SERVICE_UNIT,
        },
        "calendar": backup_calendar(),
        "timeout": BACKUP_SERVICE_TIMEOUT_SECONDS,
        "health_path": api_route_path(HEALTH_PATH),
        "health_status": HEALTH_HTTP_STATUS,
        "https_port": PRIVATE_HTTPS_PORT,
        "host_tag": TAILNET_HOST_TAG,
        "uv_version": UV_VERSION,
        "activation_timeout": ACTIVATION_TIMEOUT_SECONDS,
        "runtime_keys": {
            "worker_database_pool_size": WORKER_DATABASE_POOL_SIZE_ENV,
            "live_redis_shards": LIVE_REDIS_SHARDS_ENV,
            "origin": AUTH_ORIGIN_ENV,
            "http_port": HTTP_PORT_ENV,
            "secrets": SECRETS_DIRECTORY_ENV,
            "smtp_host": SMTP_HOST_ENV,
            "smtp_port": SMTP_PORT_ENV,
            "smtp_security": SMTP_SECURITY_ENV,
            "smtp_from": SMTP_FROM_ENV,
        },
        "secret_files": {field.name.lower(): field.value for field in SecretFile},
        "transport_files": {
            field.name.lower(): field.value for field in HostTransportFile
        },
        "backup_remote": BACKUP_REMOTE_NAME,
        "sftp_backend": SFTP_BACKEND,
        "paths": {
            "cloudflare": str(CLOUDFLARE_CONFIGURATION_DIRECTORY),
            "active_manifest": MANIFEST_NAME,
            "registry": REGISTRY_AUTH_DIRECTORY_NAME,
            "current": CURRENT_RELEASE_NAME,
            "releases": RELEASES_DIRECTORY_NAME,
            "runtime": RUNTIME_CONFIGURATION_NAME,
            "operations": OPERATIONS_CONFIGURATION_NAME,
            "staging": STAGING_DIRECTORY_NAME,
            "secrets": SECRETS_DIRECTORY_NAME,
            "bundle": RELEASE_BUNDLE_FILENAME,
        },
        "operations": {
            operation.name.lower(): operation.value for operation in HostOperation
        },
        "backup_timers": list(BACKUP_TIMER_UNITS),
        "backup_services": list(BACKUP_SERVICE_UNITS),
        "timers": [unit for unit in REQUIRED_ACTIVE_UNITS if unit.endswith(".timer")],
        "services": list(REQUIRED_COMPLETED_UNITS),
    }
