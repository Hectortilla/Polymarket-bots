"""Explicit same-origin deployment configuration."""

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv6Address
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from starlette.applications import Starlette


class OriginScheme(StrEnum):
    HTTP = "http"
    HTTPS = "https"


AUTH_ORIGIN_ENV = "POLYBOT_AUTH_ORIGIN"
AUTH_ALLOW_HTTP_ENV = "POLYBOT_AUTH_ALLOW_HTTP"
DEFAULT_ORIGIN_PORTS = {OriginScheme.HTTP: 80, OriginScheme.HTTPS: 443}


@dataclass(frozen=True)
class AuthSettings:
    origin: str
    allow_http: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", self._canonical_origin())

    @property
    def secure_cookie(self) -> bool:
        return urlsplit(self.origin).scheme == OriginScheme.HTTPS

    @classmethod
    def for_app(cls, app: "Starlette") -> "AuthSettings":
        if not hasattr(app.state, "auth_settings"):
            app.state.auth_settings = cls.from_env()
        return app.state.auth_settings

    @classmethod
    def from_env(cls) -> "AuthSettings":
        origin = os.environ.get(AUTH_ORIGIN_ENV)
        if not origin:
            raise ValueError(f"{AUTH_ORIGIN_ENV} is not configured")
        value = os.environ.get(AUTH_ALLOW_HTTP_ENV, "false")
        if value not in {"true", "false"}:
            raise ValueError(f"{AUTH_ALLOW_HTTP_ENV} must be true or false")
        return cls(origin, value == "true")

    def _canonical_origin(self) -> str:
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme not in DEFAULT_ORIGIN_PORTS
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(character.isspace() for character in self.origin)
            or parsed.netloc.endswith(":")
        ):
            raise ValueError(
                "auth origin must be an exact HTTP(S) origin without a path"
            )
        if parsed.scheme == OriginScheme.HTTP and not self.allow_http:
            raise ValueError("HTTP auth requires explicit local development opt-in")
        # Reject nonnumeric and out-of-range ports at config ingress.
        port = parsed.port
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{IPv6Address(host).compressed}]"
        elif re.fullmatch(r"[a-z0-9.-]+", host) is None:
            raise ValueError("auth origin contains an invalid hostname")
        default_port = DEFAULT_ORIGIN_PORTS[parsed.scheme]
        suffix = "" if port is None or port == default_port else f":{port}"
        return f"{parsed.scheme}://{host}{suffix}"
