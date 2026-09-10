"""Validated process configuration; credentials are excluded from representations."""

import os
import re
from enum import StrEnum
from ipaddress import ip_address
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from api.auth.config import AuthSettings
from api.database import DATABASE_URL_ENV, configured_database_url
from api.execution.config import REDIS_URL_ENV, configured_redis_url
from api.limits.policy import PAPER_BETA
from api.runs.lease_policy import DEFAULT_HEARTBEAT_SECONDS, DEFAULT_LEASE_SECONDS


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


ENVIRONMENT_ENV = "POLYBOT_ENVIRONMENT"
RELEASE_ID_ENV = "POLYBOT_RELEASE_ID"
RELEASE_ID_PATTERN = r"[a-f0-9]{40,64}"
WORKER_CONCURRENCY_ENV = "POLYBOT_WORKER_CONCURRENCY"
HEARTBEAT_SECONDS_ENV = "POLYBOT_HEARTBEAT_SECONDS"
LEASE_SECONDS_ENV = "POLYBOT_LEASE_SECONDS"
PROXY_ADDRESS_ENV = "POLYBOT_PROXY_ADDRESS"
STORAGE_PROBE_PATH_ENV = "POLYBOT_STORAGE_PROBE_PATH"
DEFAULT_STORAGE_PROBE_PATH = Path("/")
DEPLOYMENT_STORAGE_PROBE_PATH = Path("/storage")
DEFAULT_WORKER_CONCURRENCY = PAPER_BETA.global_active_runs

API_WORKERS = 2
API_PORT = 8000


class StartupSettings(BaseModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    database_url: SecretStr
    redis_url: SecretStr
    environment: Environment = Environment.DEVELOPMENT
    release_id: str = "development"
    worker_concurrency: int = Field(default=DEFAULT_WORKER_CONCURRENCY, gt=0)
    heartbeat_seconds: float = Field(
        default=DEFAULT_HEARTBEAT_SECONDS, gt=0, allow_inf_nan=False
    )
    lease_seconds: float = Field(
        default=DEFAULT_LEASE_SECONDS, gt=0, allow_inf_nan=False
    )
    proxy_address: str | None = None
    storage_probe_path: Path = DEFAULT_STORAGE_PROBE_PATH

    @field_validator("storage_probe_path", mode="before")
    @classmethod
    def validate_storage_path(cls, value: str | Path) -> Path:
        path = Path(value)
        if not str(value).strip() or not path.is_absolute():
            raise ValueError("storage probe requires a nonempty absolute path")
        return Path(os.path.normpath(path))

    @model_validator(mode="after")
    def validate_deployment(self) -> Self:
        if self.lease_seconds <= self.heartbeat_seconds:
            raise ValueError("lease interval must exceed heartbeat interval")
        if self.proxy_address is not None:
            ip_address(self.proxy_address)
        if self.environment is Environment.PRODUCTION:
            if re.fullmatch(RELEASE_ID_PATTERN, self.release_id) is None:
                raise ValueError("production requires an immutable release identifier")
            if self.proxy_address is None:
                raise ValueError(
                    "production requires one explicit trusted proxy address"
                )
        return self

    @classmethod
    def from_env(cls) -> Self:
        # URL adapters own parsing; no connection strings enter validation errors.
        try:
            database_url = configured_database_url().render_as_string(
                hide_password=False
            )
            redis_url = configured_redis_url()
        except Exception:
            raise ValueError(
                "invalid or missing database/Redis configuration"
            ) from None
        settings = cls(
            database_url=SecretStr(database_url),
            redis_url=SecretStr(redis_url),
            environment=os.getenv(ENVIRONMENT_ENV, Environment.DEVELOPMENT),
            release_id=os.getenv(RELEASE_ID_ENV, "development"),
            worker_concurrency=os.getenv(
                WORKER_CONCURRENCY_ENV, DEFAULT_WORKER_CONCURRENCY
            ),
            heartbeat_seconds=os.getenv(
                HEARTBEAT_SECONDS_ENV, DEFAULT_HEARTBEAT_SECONDS
            ),
            lease_seconds=os.getenv(LEASE_SECONDS_ENV, DEFAULT_LEASE_SECONDS),
            proxy_address=os.getenv(PROXY_ADDRESS_ENV),
            storage_probe_path=os.getenv(
                STORAGE_PROBE_PATH_ENV, DEFAULT_STORAGE_PROBE_PATH
            ),
        )
        if settings.environment is Environment.PRODUCTION:
            auth = AuthSettings.from_env()
            if auth.allow_http or not auth.secure_cookie:
                raise ValueError(
                    "production requires HTTPS and forbids HTTP auth opt-in"
                )
            for name in (DATABASE_URL_ENV, REDIS_URL_ENV):
                if not os.getenv(f"{name}_FILE"):
                    raise ValueError(f"production requires {name}_FILE")
        return settings
