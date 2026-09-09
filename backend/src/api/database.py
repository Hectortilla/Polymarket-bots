"""Shared control-plane PostgreSQL configuration boundary."""

from sqlalchemy.engine import URL, make_url

from api.deployment.secrets import configured_secret

DATABASE_URL_ENV = "POLYBOT_DATABASE_URL"
POSTGRESQL_BACKEND_NAME = "postgresql"
ASYNC_POSTGRESQL_DRIVER_NAME = "postgresql+asyncpg"


def configured_database_url() -> URL:
    raw_url = configured_secret(DATABASE_URL_ENV)
    if raw_url is None:
        raise ValueError(f"{DATABASE_URL_ENV} is not configured")
    return async_database_url(raw_url)


def async_database_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.get_backend_name() != POSTGRESQL_BACKEND_NAME:
        raise ValueError("control-plane database requires a PostgreSQL URL")
    if not (url.database or "").strip():
        raise ValueError("control-plane database requires a database name")
    return url.set(drivername=ASYNC_POSTGRESQL_DRIVER_NAME)
