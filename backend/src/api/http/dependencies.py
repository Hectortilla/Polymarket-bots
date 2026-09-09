"""FastAPI dependency and resource-lifecycle wiring."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from polybot.polymarket.discovery import MarketDiscovery
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.auth.config import AuthSettings
from api.deployment.settings import StartupSettings
from api.execution.launcher import RunLauncher
from api.io_policy import (
    DATABASE_CONNECT_ARGS,
    DEPENDENCY_TIMEOUT_SECONDS,
    REDIS_SOCKET_OPTIONS,
)


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    AuthSettings.for_app(app)
    if not hasattr(app.state, "session_factory") or not hasattr(app.state, "redis"):
        app.state.startup_settings = await asyncio.to_thread(StartupSettings.from_env)
    owned_engine: AsyncEngine | None = None
    owned_redis: Redis | None = None
    owned_discovery: MarketDiscovery | None = None
    if not hasattr(app.state, "session_factory"):
        owned_engine = create_async_engine(
            app.state.startup_settings.database_url.get_secret_value(),
            hide_parameters=True,
            connect_args=DATABASE_CONNECT_ARGS,
            pool_timeout=DEPENDENCY_TIMEOUT_SECONDS,
        )
        app.state.session_factory = async_sessionmaker(
            owned_engine,
            expire_on_commit=False,
        )
    if not hasattr(app.state, "redis"):
        owned_redis = Redis.from_url(
            app.state.startup_settings.redis_url.get_secret_value(),
            **REDIS_SOCKET_OPTIONS,
        )
        app.state.redis = owned_redis
    if not hasattr(app.state, "launcher"):
        app.state.launcher = await asyncio.to_thread(_default_launcher)
    if not hasattr(app.state, "market_discovery"):
        owned_discovery = MarketDiscovery()
        app.state.market_discovery = owned_discovery
    try:
        yield
    finally:
        try:
            if owned_discovery is not None:
                await owned_discovery.close()
        finally:
            if owned_redis is not None:
                await owned_redis.aclose()
            if owned_engine is not None:
                await owned_engine.dispose()


def _default_launcher() -> RunLauncher:
    from api.execution.taskiq_app import TaskiqRunLauncher

    return TaskiqRunLauncher()


def _session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def _redis(request: Request) -> Redis:
    return request.app.state.redis


def _launcher(request: Request) -> RunLauncher:
    return request.app.state.launcher


def _market_discovery(request: Request) -> MarketDiscovery:
    return request.app.state.market_discovery


SessionFactoryDependency = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(_session_factory),
]
RedisDependency = Annotated[Redis, Depends(_redis)]
LauncherDependency = Annotated[RunLauncher, Depends(_launcher)]
MarketDiscoveryDependency = Annotated[MarketDiscovery, Depends(_market_discovery)]
