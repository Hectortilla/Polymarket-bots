"""FastAPI application assembly for the private paper-run control plane."""

from fastapi import FastAPI
from api.http.routes.graph_preview import (
    router as graph_preview_router,
)
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot.polymarket.discovery import MarketDiscovery
from api.http.dependencies import application_lifespan
from api.http.routes.bots import router as bots_router
from api.http.routes.catalog import router as catalog_router
from api.http.routes.graph_templates import (
    router as graph_templates_router,
)
from api.http.routes.events import router as events_router
from api.http.routes.health import router as health_router
from api.http.routes.markets import router as markets_router
from api.http.routes.paths import API_PREFIX
from api.http.routes.runs import router as runs_router
from api.execution.launcher import RunLauncher


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    redis: Redis | None = None,
    launcher: RunLauncher | None = None,
    market_discovery: MarketDiscovery | None = None,
) -> FastAPI:
    application = FastAPI(
        title="Polybot Control Plane",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=application_lifespan,
    )
    if session_factory is not None:
        application.state.session_factory = session_factory
    if redis is not None:
        application.state.redis = redis
    if launcher is not None:
        application.state.launcher = launcher
    if market_discovery is not None:
        application.state.market_discovery = market_discovery
    for router in (
        graph_preview_router,
        catalog_router,
        markets_router,
        graph_templates_router,
        bots_router,
        runs_router,
        events_router,
        health_router,
    ):
        application.include_router(router, prefix=API_PREFIX)
    return application


app = create_app()
