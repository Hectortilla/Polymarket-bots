"""Application process names shared by deployment and release orchestration."""

from enum import StrEnum


class DeploymentService(StrEnum):
    API = "api"
    WORKER = "worker"
    RECOVERY = "recovery"
    MIGRATE = "migrate"
    CHECK = "check"


ENTRYPOINT_SERVICE = "entrypoint"
APPLICATION_SERVICES = (
    ENTRYPOINT_SERVICE,
    DeploymentService.API,
    DeploymentService.WORKER,
    DeploymentService.RECOVERY,
)
