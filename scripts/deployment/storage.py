"""Container storage coordinates and runtime-secret filenames."""

from enum import StrEnum
from urllib.parse import quote

from api.deployment.services import POSTGRES_SERVICE, REDIS_SERVICE


class SecretFile(StrEnum):
    DATABASE_URL = "database_url"
    POSTGRES_PASSWORD = "postgres_password"
    REDIS_URL = "redis_url"
    SMTP_USERNAME = "smtp_username"
    SMTP_PASSWORD = "smtp_password"


POSTGRES_USER = "polybot"
POSTGRES_DATABASE = "polybot"
POSTGRES_PORT = 5432
REDIS_PORT = 6379
REDIS_DATABASE = 0


def database_url(password: str) -> str:
    return f"postgresql+asyncpg://{POSTGRES_USER}:{quote(password, safe='')}@{POSTGRES_SERVICE}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"


def redis_url() -> str:
    return f"redis://{REDIS_SERVICE}:{REDIS_PORT}/{REDIS_DATABASE}"
