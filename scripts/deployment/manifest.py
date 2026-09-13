"""Validated host runtime configuration, separate from release activation."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

from api.auth.config import AUTH_ORIGIN_ENV, AuthSettings
from api.auth.mail.config import (
    DEFAULT_SMTP_SECURITY,
    SMTP_FROM_ENV,
    SMTP_HOST_ENV,
    SMTP_PORT_ENV,
    SMTP_SECURITY_ENV,
    SmtpSettings,
)

from scripts.deployment.dotenv import read_values
from scripts.deployment.images import ImagePolicy, ReleaseImages

HTTP_PORT_ENV = "POLYBOT_HTTP_PORT"
SECRETS_DIRECTORY_ENV = "POLYBOT_SECRETS_DIR"
DEFAULT_HTTP_PORT = 8081
DEFAULT_AUTH_ORIGIN = "https://localhost:8443"
DEFAULT_SMTP_PORT = 587


@dataclass(frozen=True)
class RuntimeManifest:
    images: ReleaseImages
    auth: AuthSettings
    smtp: SmtpSettings
    secrets_directory: Path
    extra_values: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def read(
        cls,
        path: Path,
        *,
        policy: ImagePolicy = ImagePolicy.LOCAL_OR_REGISTRY,
        required_mode: int | None = None,
    ) -> "RuntimeManifest":
        return cls.from_values(
            read_values(path, required_mode=required_mode), policy=policy
        )

    @classmethod
    def from_values(
        cls, values: Mapping[str, str], *, policy: ImagePolicy
    ) -> "RuntimeManifest":
        images = ReleaseImages.from_values(values, policy=policy)
        auth = AuthSettings(values.get(AUTH_ORIGIN_ENV, ""))
        port = int(values.get(HTTP_PORT_ENV) or DEFAULT_HTTP_PORT)
        if not 1024 <= port <= 65535:
            raise ValueError("internal HTTP port must be between 1024 and 65535")
        directory = Path(values.get(SECRETS_DIRECTORY_ENV, ""))
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError(
                "runtime secrets directory must be an existing absolute path"
            )
        smtp = SmtpSettings(
            host=values.get(SMTP_HOST_ENV, ""),
            port=values.get(SMTP_PORT_ENV) or DEFAULT_SMTP_PORT,
            sender=values.get(SMTP_FROM_ENV, ""),
            security=values.get(SMTP_SECURITY_ENV) or DEFAULT_SMTP_SECURITY,
        )
        settings = cls(images, auth, smtp, directory)
        known_fields = settings.to_values().keys() - {HTTP_PORT_ENV}
        extras = {
            key: value for key, value in values.items() if key not in known_fields
        }
        return replace(settings, extra_values=MappingProxyType(extras))

    def with_images(self, candidate: ReleaseImages) -> "RuntimeManifest":
        self.images.require_same_infrastructure(candidate)
        return replace(self, images=candidate)

    def to_values(self) -> dict[str, str]:
        return {
            **self.extra_values,
            **self.images.to_values(),
            AUTH_ORIGIN_ENV: self.auth.origin,
            HTTP_PORT_ENV: str(
                int(self.extra_values.get(HTTP_PORT_ENV) or DEFAULT_HTTP_PORT)
            ),
            SECRETS_DIRECTORY_ENV: str(self.secrets_directory),
            SMTP_HOST_ENV: self.smtp.host,
            SMTP_PORT_ENV: str(self.smtp.port),
            SMTP_SECURITY_ENV: self.smtp.security.value,
            SMTP_FROM_ENV: str(self.smtp.sender),
        }
