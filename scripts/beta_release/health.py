"""Normalize Docker Compose status before applying deployment readiness policy."""

import json
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.compose_project import ComposeProject
from dataclasses import dataclass

from api.deployment.services import (
    APPLICATION_SERVICES,
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)

from scripts.deployment.errors import DeploymentInputError

HEALTHCHECK_SERVICES = frozenset(
    (DeploymentService.API, ENTRYPOINT_SERVICE, POSTGRES_SERVICE, REDIS_SERVICE)
)
REQUIRED_SERVICES = (*APPLICATION_SERVICES, POSTGRES_SERVICE, REDIS_SERVICE)


@dataclass(frozen=True)
class ComposeServiceStatus:
    service: str
    running: bool
    healthy: bool


@dataclass(frozen=True)
class ComposeStatus:
    services: dict[str, ComposeServiceStatus]

    @classmethod
    def read(cls, compose: "ComposeProject") -> "ComposeStatus":
        output = subprocess.check_output(
            compose.command("ps", "--all", "--format", "json"),
            env=compose.environment,
            text=True,
            timeout=30,
        )
        return cls(parse_compose_status(output))


def parse_compose_status(output: str) -> dict[str, ComposeServiceStatus]:
    try:
        rows = (
            json.loads(output)
            if output.lstrip().startswith("[")
            else [json.loads(line) for line in output.splitlines() if line.strip()]
        )
    except (ValueError, TypeError):
        raise DeploymentInputError("invalid Compose status JSON") from None
    if not isinstance(rows, list):
        raise DeploymentInputError("Compose status must contain service records")
    services = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("Service"), str)
            or not row["Service"]
            or not isinstance(row.get("State"), str)
            or not isinstance(row.get("Health", ""), str)
        ):
            raise DeploymentInputError("invalid Compose service status")
        name = row["Service"]
        if name in services:
            raise DeploymentInputError("duplicate Compose service status")
        health = row.get("Health", "")
        services[name] = ComposeServiceStatus(
            name,
            row["State"] == "running",
            health == "healthy" or (not health and name not in HEALTHCHECK_SERVICES),
        )
    return services
