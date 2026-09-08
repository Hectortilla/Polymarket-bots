"""Reject destructive test setup against targets outside the local test boundary."""

from urllib.parse import urlsplit

from api.auth.policy import AUTH_RATE_LIMIT_KEY_PREFIX
from api.database import async_database_url
from redis.asyncio import Redis
from sqlalchemy.engine import URL

LOCAL_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def disposable_postgres_url(raw_url: str) -> URL:
    url = async_database_url(raw_url)
    if url.host not in LOCAL_TEST_HOSTS or not (url.database or "").endswith("_test"):
        raise ValueError("acceptance requires a local disposable *_test database")
    return url


def disposable_redis_url(raw_url: str) -> str:
    url = urlsplit(raw_url)
    database = url.path.removeprefix("/")
    if (
        url.scheme not in {"redis", "rediss"}
        or url.hostname not in LOCAL_TEST_HOSTS
        or not database.isascii()
        or not database.isdecimal()
        or int(database) <= 0
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "acceptance requires an explicit nonzero local Redis test database"
        )
    if url.port is None:
        raise ValueError("acceptance requires an explicit Redis test port")
    return raw_url


async def clear_auth_attempts(redis: Redis) -> None:
    async for key in redis.scan_iter(AUTH_RATE_LIMIT_KEY_PREFIX + "*"):
        await redis.delete(key)
