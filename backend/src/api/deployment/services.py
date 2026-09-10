"""Compose service names and application process subsets for release orchestration."""

from enum import StrEnum


class DeploymentService(StrEnum):
    API = "api"
    WORKER = "worker"
    RECOVERY = "recovery"
    MIGRATE = "migrate"
    CHECK = "check"


POSTGRES_SERVICE = "postgres"
REDIS_SERVICE = "redis"

ENTRYPOINT_SERVICE = "entrypoint"
APPLICATION_SERVICES = (
    ENTRYPOINT_SERVICE,
    DeploymentService.API,
    DeploymentService.WORKER,
    DeploymentService.RECOVERY,
)
