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
from scripts.deployment.ingress import IngressMode
from scripts.deployment.network import HEALTH_HTTP_STATUS
from scripts.deployment.tailscale import PRIVATE_HTTPS_PORT, PrivateServe, TailnetStatus
from scripts.deployment.units import CLOUDFLARE_SERVICE_UNIT
from scripts.host_operations.config import HostOperationsConfig
from scripts.host_operations.contracts import (
    BACKUP_SERVICE_UNITS,
    BACKUP_TIMER_UNITS,
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
            if not self.config.backups_enabled and unit in BACKUP_TIMER_UNITS:
                continue
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
        status.require_origin(self.config.tailnet_origin)
        serve = PrivateServe.from_record(
            json.loads(
                subprocess.check_output(
                    ["tailscale", "serve", "status", "--json"],
                    timeout=HOST_COMMAND_TIMEOUT_SECONDS,
                )
            )
        )
        serve.require_endpoint(self.config.tailnet_origin, self.config.http_port)
        if self.config.ingress is IngressMode.CLOUDFLARE:
            result = subprocess.run(
                ["systemctl", "is-active", "--quiet", CLOUDFLARE_SERVICE_UNIT],
                check=False,
                timeout=HOST_COMMAND_TIMEOUT_SECONDS,
            )
            expected = 0 if self.config.public_enabled else 3
            if result.returncode != expected:
                raise RuntimeError(
                    "Cloudflare connector differs from public access policy"
                )

        completed_units = [
            unit
            for unit in REQUIRED_COMPLETED_UNITS
            if self.config.backups_enabled or unit not in BACKUP_SERVICE_UNITS
        ]
        for unit in completed_units:
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
                *completed_units,
            ],
            check=False,
            timeout=HOST_COMMAND_TIMEOUT_SECONDS,
        )
        # systemctl is-failed returns 1 only when none of the named units failed.
        # Unit existence is checked separately; other statuses also fail closed.
        if failed.returncode != 1:
            raise RuntimeError("a required backup unit failed or is unavailable")

    def https(self) -> None:
        origin = self.config.readiness_origin
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
                raise RuntimeError("HTTPS readiness failed")


def certificate_expiry(record: object) -> float:
    if not isinstance(record, dict) or not isinstance(record.get("notAfter"), str):
        raise DeploymentInputError("invalid HTTPS certificate expiry")
    try:
        return ssl.cert_time_to_seconds(record["notAfter"])
    except (ValueError, OverflowError):
        raise DeploymentInputError("invalid HTTPS certificate expiry") from None
