"""Validated Redis configuration used by Taskiq and worker event delivery."""

import os
from urllib.parse import urlsplit


REDIS_URL_ENV = "POLYBOT_REDIS_URL"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
REDIS_URL_SCHEMES = frozenset({"redis", "rediss"})


def configured_redis_url() -> str:
    url = os.getenv(REDIS_URL_ENV, DEFAULT_REDIS_URL)
    parsed = urlsplit(url)
    if parsed.scheme not in REDIS_URL_SCHEMES:
        raise ValueError(f"{REDIS_URL_ENV} must use redis:// or rediss://")
    if parsed.hostname is None:
        raise ValueError(f"{REDIS_URL_ENV} must include a host")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError(f"{REDIS_URL_ENV} has an invalid port") from error
    database_path = parsed.path.removeprefix("/")
    if database_path and not database_path.isdecimal():
        raise ValueError(f"{REDIS_URL_ENV} must use a numeric Redis database")
    return url
