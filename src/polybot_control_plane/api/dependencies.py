"""FastAPI dependency and resource-lifecycle wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polybot_control_plane.database import configured_database_url
from polybot_control_plane.execution.config import configured_redis_url
from polybot_control_plane.execution.launcher import RunLauncher


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    owned_engine: AsyncEngine | None = None
    owned_redis: Redis | None = None
    if not hasattr(app.state, "session_factory"):
        owned_engine = create_async_engine(configured_database_url())
        app.state.session_factory = async_sessionmaker(
            owned_engine,
            expire_on_commit=False,
        )
    if not hasattr(app.state, "redis"):
        owned_redis = Redis.from_url(configured_redis_url())
        app.state.redis = owned_redis
    if not hasattr(app.state, "launcher"):
        app.state.launcher = _default_launcher()
    try:
        yield
    finally:
        if owned_redis is not None:
            await owned_redis.aclose()
        if owned_engine is not None:
            await owned_engine.dispose()


def _default_launcher() -> RunLauncher:
    from polybot_control_plane.execution.taskiq_app import TaskiqRunLauncher

    return TaskiqRunLauncher()


def _session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def _redis(request: Request) -> Redis:
    return request.app.state.redis


def _launcher(request: Request) -> RunLauncher:
    return request.app.state.launcher


SessionFactoryDependency = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(_session_factory),
]
RedisDependency = Annotated[Redis, Depends(_redis)]
LauncherDependency = Annotated[RunLauncher, Depends(_launcher)]
