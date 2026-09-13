"""Tailscale CLI JSON boundary for the private persisted HTTPS endpoint."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict
from urllib.parse import urlsplit

from api.auth.config import AuthSettings

from scripts.deployment.errors import DeploymentInputError


class BackendState(StrEnum):
    NO_STATE = "NoState"
    IN_USE_OTHER_USER = "InUseOtherUser"
    NEEDS_LOGIN = "NeedsLogin"
    NEEDS_MACHINE_AUTH = "NeedsMachineAuth"
    STOPPED = "Stopped"
    STARTING = "Starting"
    RUNNING = "Running"


class EnrollmentStatus(TypedDict):
    running: bool


class ServeStatus(TypedDict):
    configured: bool


PRIVATE_HTTPS_PORT = 443
TAILNET_HOST_TAG = "tag:polybot"
TAILNET_CI_TAG = "tag:polybot-ci"


def validate_private_origin(value: str) -> str:
    origin = AuthSettings(value).origin
    parsed = urlsplit(origin)
    if (
        origin != value
        or parsed.port is not None
        or re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.){1,}ts\.net", parsed.hostname or ""
        )
        is None
    ):
        raise DeploymentInputError("an exact private HTTPS ts.net origin is required")
    return origin


@dataclass(frozen=True)
class TailnetStatus:
    running: bool
    dns_name: str | None

    @classmethod
    def from_record(cls, record: object) -> "TailnetStatus":
        if not isinstance(record, dict) or not isinstance(
            record.get("BackendState"), str
        ):
            raise DeploymentInputError("invalid Tailscale status")
        own = record.get("Self")
        if own is not None and (
            not isinstance(own, dict) or not isinstance(own.get("DNSName"), str)
        ):
            raise DeploymentInputError("invalid Tailscale identity")
        return cls(
            BackendState(record["BackendState"]) is BackendState.RUNNING,
            own["DNSName"].rstrip(".") if own else None,
        )

    def require_origin(self, origin: str) -> None:
        if not self.running or self.dns_name != urlsplit(origin).hostname:
            raise DeploymentInputError(
                "Tailscale identity does not match the private origin"
            )


@dataclass(frozen=True)
class PrivateServe:
    https_ports: frozenset[str]
    proxies: dict[str, dict[str, str]]

    @classmethod
    def from_record(cls, record: object) -> "PrivateServe":
        if not isinstance(record, dict):
            raise DeploymentInputError("invalid Tailscale Serve configuration")
        funnel = mapping_field(record, "AllowFunnel")
        if any(type(enabled) is not bool for enabled in funnel.values()):
            raise DeploymentInputError("invalid Funnel configuration")
        if any(funnel.values()):
            raise DeploymentInputError("public Funnel must be disabled")
        # The app owns one persisted endpoint. Reject alternate transient or
        # service configurations rather than overlooking a nested public route.
        if mapping_field(record, "Foreground") or mapping_field(record, "Services"):
            raise DeploymentInputError(
                "only persisted host Serve configuration is supported"
            )
        ports = mapping_field(record, "TCP")
        https_ports = set()
        for port, config in ports.items():
            if (
                not isinstance(config, dict)
                or type(config.get("HTTPS", False)) is not bool
            ):
                raise DeploymentInputError("invalid Serve TCP configuration")
            if config.get("HTTPS", False):
                https_ports.add(port)
        proxies = {}
        for host, config in mapping_field(record, "Web").items():
            if not isinstance(config, dict):
                raise DeploymentInputError("invalid Serve web configuration")
            handlers = mapping_field(config, "Handlers")
            proxies[host] = {}
            for mount, handler in handlers.items():
                if not isinstance(handler, dict) or not isinstance(
                    handler.get("Proxy", ""), str
                ):
                    raise DeploymentInputError("invalid Serve handler")
                proxies[host][mount] = handler.get("Proxy", "")
        return cls(frozenset(https_ports), proxies)

    def matches(self, origin: str, http_port: int) -> bool:
        host = f"{urlsplit(origin).hostname}:{PRIVATE_HTTPS_PORT}"
        return (
            str(PRIVATE_HTTPS_PORT) in self.https_ports
            and self.proxies.get(host, {}).get("/") == f"http://127.0.0.1:{http_port}"
        )

    def require_endpoint(self, origin: str, http_port: int) -> None:
        if not self.matches(origin, http_port):
            raise DeploymentInputError(
                "private Serve endpoint differs from configured origin or proxy"
            )


def mapping_field(record: dict, field: str) -> dict:
    value = record.get(field, {})
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DeploymentInputError("invalid Tailscale configuration mapping")
    return value
