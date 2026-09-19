"""FastAPI dependency and resource-lifecycle wiring."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from polybot.polymarket.discovery import MarketDiscovery
from polybot.polymarket.wallet_discovery import WalletDiscovery
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.admin.application import install_admin
from api.auth.config import AuthSettings
from api.auth.development import DevelopmentAccountStore
from api.auth.mail import AccountMailer
from api.deployment.settings import Environment, StartupSettings
from api.events.live.connections import LiveConnections
from api.events.live.routing import LiveShardRouter
from api.events.terminal_wakes import TerminalWakePublisher
from api.execution.launcher import RunLauncher
from api.http.sse.hub import LiveSubscriptionHub
from api.io_policy import (
    DATABASE_CONNECT_ARGS,
    DEPENDENCY_TIMEOUT_SECONDS,
    REDIS_CONTROL_POOL_SIZE,
    REDIS_SOCKET_OPTIONS,
)


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    AuthSettings.for_app(app)
    if not hasattr(app.state, "session_factory") or not hasattr(app.state, "redis"):
        app.state.startup_settings = await asyncio.to_thread(StartupSettings.from_env)
    startup_settings = getattr(app.state, "startup_settings", None)
    if (
        startup_settings is not None
        and startup_settings.environment is Environment.PRODUCTION
    ):
        await AccountMailer.for_app(app)
    async with AsyncExitStack() as cleanup:
        if not hasattr(app.state, "session_factory"):
            engine = create_async_engine(
                app.state.startup_settings.database_url.get_secret_value(),
                hide_parameters=True,
                connect_args=DATABASE_CONNECT_ARGS,
                pool_timeout=DEPENDENCY_TIMEOUT_SECONDS,
            )
            cleanup.push_async_callback(engine.dispose)
            app.state.session_factory = async_sessionmaker(
                engine, expire_on_commit=False
            )
        if not hasattr(app.state, "redis"):
            redis = Redis.from_url(
                app.state.startup_settings.redis_url.get_secret_value(),
                max_connections=REDIS_CONTROL_POOL_SIZE,
                **REDIS_SOCKET_OPTIONS,
            )
            cleanup.push_async_callback(redis.aclose)
            app.state.redis = redis
        if not hasattr(app.state, "live_subscription_hub"):
            if startup_settings is not None:
                live = LiveConnections(startup_settings)
                cleanup.push_async_callback(live.close)
                router, clients = live.router, live.clients
            else:
                router, clients = (
                    LiveShardRouter(("injected-redis",)),
                    (app.state.redis,),
                )
            hub = LiveSubscriptionHub(router, clients, app.state.redis)
            app.state.live_subscription_hub = hub
            cleanup.push_async_callback(hub.close)
            await hub.start()
        else:
            cleanup.push_async_callback(app.state.live_subscription_hub.close)
        if not hasattr(app.state, "launcher"):
            app.state.launcher = await asyncio.to_thread(_default_launcher)
        if not hasattr(app.state, "market_discovery"):
            discovery = MarketDiscovery()
            cleanup.push_async_callback(discovery.close)
            app.state.market_discovery = discovery
        if not hasattr(app.state, "wallet_discovery"):
            wallet_discovery = WalletDiscovery()
            cleanup.push_async_callback(wallet_discovery.close)
            app.state.wallet_discovery = wallet_discovery
        terminal_wakes = TerminalWakePublisher(
            app.state.session_factory, app.state.redis
        )
        cleanup.push_async_callback(terminal_wakes.close)
        await terminal_wakes.start()
        install_admin(app)
        if startup_settings is not None and startup_settings.seed_development_account:
            async with app.state.session_factory() as session:
                await DevelopmentAccountStore(session).ensure_account()
        yield


def _default_launcher() -> RunLauncher:
    from api.execution.taskiq_app import TaskiqRunLauncher

    return TaskiqRunLauncher()


def _session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def _redis(request: Request) -> Redis:
    return request.app.state.redis


def _live_subscription_hub(request: Request) -> LiveSubscriptionHub:
    return request.app.state.live_subscription_hub


def _launcher(request: Request) -> RunLauncher:
    return request.app.state.launcher


def _market_discovery(request: Request) -> MarketDiscovery:
    return request.app.state.market_discovery


def _wallet_discovery(request: Request) -> WalletDiscovery:
    return request.app.state.wallet_discovery


SessionFactoryDependency = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(_session_factory),
]
RedisDependency = Annotated[Redis, Depends(_redis)]
LiveSubscriptionHubDependency = Annotated[
    LiveSubscriptionHub, Depends(_live_subscription_hub)
]
LauncherDependency = Annotated[RunLauncher, Depends(_launcher)]
MarketDiscoveryDependency = Annotated[MarketDiscovery, Depends(_market_discovery)]


WalletDiscoveryDependency = Annotated[WalletDiscovery, Depends(_wallet_discovery)]
