"""Systemd, Tailscale, and HTTPS boundary checks."""

import json
import socket
import ssl
import subprocess
import urllib.request
from datetime import UTC, datetime
from urllib.parse import urlsplit

from api.http.routes.paths import HEALTH_PATH, api_route_path

from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.network import HEALTH_HTTP_STATUS
from scripts.deployment.tailscale import PRIVATE_HTTPS_PORT, PrivateServe, TailnetStatus
from scripts.host_operations.config import HostOperationsConfig
from scripts.host_operations.contracts import (
    REQUIRED_ACTIVE_UNITS,
    REQUIRED_COMPLETED_UNITS,
)
from scripts.host_operations.policy import (
    CERTIFICATE_WARNING_SECONDS,
    HOST_COMMAND_TIMEOUT_SECONDS,
    HTTPS_PROBE_TIMEOUT_SECONDS,
)


class HostProbes:
    def __init__(self, config: HostOperationsConfig) -> None:
        self.config = config

    def services(self) -> None:
        # Check units separately: a multi-unit is-active succeeds when any one is active.
        for unit in REQUIRED_ACTIVE_UNITS:
            subprocess.run(
                ["systemctl", "is-active", "--quiet", unit],
                check=True,
                timeout=HOST_COMMAND_TIMEOUT_SECONDS,
            )
        status = TailnetStatus.from_record(
            json.loads(
                subprocess.check_output(
                    ["tailscale", "status", "--json"],
                    timeout=HOST_COMMAND_TIMEOUT_SECONDS,
                )
            )
        )
        status.require_origin(self.config.origin)
        serve = PrivateServe.from_record(
            json.loads(
                subprocess.check_output(
                    ["tailscale", "serve", "status", "--json"],
                    timeout=HOST_COMMAND_TIMEOUT_SECONDS,
                )
            )
        )
        serve.require_endpoint(self.config.origin, self.config.http_port)

        for unit in REQUIRED_COMPLETED_UNITS:
            subprocess.run(
                ["systemctl", "cat", unit],
                check=True,
                timeout=HOST_COMMAND_TIMEOUT_SECONDS,
                stdout=subprocess.DEVNULL,
            )
        failed = subprocess.run(
            [
                "systemctl",
                "is-failed",
                "--quiet",
                *REQUIRED_COMPLETED_UNITS,
            ],
            check=False,
            timeout=HOST_COMMAND_TIMEOUT_SECONDS,
        )
        # systemctl is-failed returns 1 only when none of the named units failed.
        # Unit existence is checked separately; other statuses also fail closed.
        if failed.returncode != 1:
            raise RuntimeError("a required backup unit failed or is unavailable")

    def https(self) -> None:
        origin = self.config.origin
        parsed = urlsplit(origin)
        context = ssl.create_default_context()
        with (
            socket.create_connection(
                (parsed.hostname, parsed.port or PRIVATE_HTTPS_PORT),
                timeout=HTTPS_PROBE_TIMEOUT_SECONDS,
            ) as connection,
            context.wrap_socket(connection, server_hostname=parsed.hostname) as tls,
        ):
            expiry = certificate_expiry(tls.getpeercert())
            if expiry - datetime.now(UTC).timestamp() < CERTIFICATE_WARNING_SECONDS:
                raise RuntimeError("HTTPS certificate renewal overdue")
        with urllib.request.urlopen(
            origin + api_route_path(HEALTH_PATH), timeout=HTTPS_PROBE_TIMEOUT_SECONDS
        ) as response:
            if response.status != HEALTH_HTTP_STATUS:
                raise RuntimeError("private HTTPS readiness failed")


def certificate_expiry(record: object) -> float:
    if not isinstance(record, dict) or not isinstance(record.get("notAfter"), str):
        raise DeploymentInputError("invalid HTTPS certificate expiry")
    try:
        return ssl.cert_time_to_seconds(record["notAfter"])
    except (ValueError, OverflowError):
        raise DeploymentInputError("invalid HTTPS certificate expiry") from None
