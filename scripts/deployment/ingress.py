"""Shared ingress configuration at inventory and host-monitor boundaries."""

import re
from enum import StrEnum
from typing import Self, cast
from urllib.parse import urlsplit

from api.auth.config import AuthSettings
from pydantic import BaseModel, Field, computed_field, model_validator

from scripts.deployment.errors import DeploymentInputError
from scripts.deployment.runtime_contracts import (
    DEFAULT_HTTP_PORT,
    HTTP_PORT_MAXIMUM,
    HTTP_PORT_MINIMUM,
)
from scripts.deployment.tailscale import validate_private_origin


class IngressMode(StrEnum):
    TAILSCALE = "tailscale"
    CLOUDFLARE = "cloudflare"


class IngressSettings(BaseModel):
    ingress: IngressMode = IngressMode.TAILSCALE
    origin: str
    tailnet_origin: str | None = None
    public_enabled: bool = Field(default=False, strict=True)
    http_port: int = Field(
        default=DEFAULT_HTTP_PORT,
        strict=True,
        ge=HTTP_PORT_MINIMUM,
        le=HTTP_PORT_MAXIMUM,
    )

    @model_validator(mode="after")
    def ingress_boundary(self) -> Self:
        tailnet = self.tailnet_origin
        if self.ingress is IngressMode.TAILSCALE:
            validate_private_origin(self.origin)
            if self.public_enabled or tailnet not in (None, self.origin):
                raise DeploymentInputError(
                    "private ingress requires one private origin"
                )
            tailnet = self.origin
        else:
            parsed = urlsplit(self.origin)
            if (
                AuthSettings(self.origin).origin != self.origin
                or parsed.port is not None
                or re.fullmatch(
                    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}",
                    parsed.hostname or "",
                )
                is None
                or (parsed.hostname or "").endswith(".ts.net")
            ):
                raise DeploymentInputError(
                    "an exact custom-domain HTTPS origin is required"
                )
            if tailnet is None:
                raise DeploymentInputError(
                    "Cloudflare requires a separate Tailscale origin"
                )
            validate_private_origin(tailnet)
        object.__setattr__(self, "tailnet_origin", tailnet)
        return self

    @computed_field
    @property
    def readiness_origin(self) -> str:
        return self.origin if self.public_enabled else cast(str, self.tailnet_origin)

    def require_bootstrapped(
        self,
        recorded: "IngressSettings",
        runtime_origin: str | None,
        runtime_port: int = DEFAULT_HTTP_PORT,
    ) -> None:
        if (
            self.ingress != recorded.ingress
            or self.origin != recorded.origin
            or self.tailnet_origin != recorded.tailnet_origin
            or self.public_enabled != recorded.public_enabled
            or self.http_port != recorded.http_port
            or self.http_port != runtime_port
            or runtime_origin != self.readiness_origin
        ):
            raise DeploymentInputError(
                "ingress configuration changed; run bootstrap before deploying"
            )
