"""FastAPI application assembly for the private paper-run control plane."""

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot_control_plane.api.dependencies import application_lifespan
from polybot_control_plane.api.routes.catalog import router as catalog_router
from polybot_control_plane.api.routes.events import router as events_router
from polybot_control_plane.api.routes.health import router as health_router
from polybot_control_plane.api.routes.paths import API_PREFIX
from polybot_control_plane.api.routes.runs import router as runs_router
from polybot_control_plane.execution.launcher import RunLauncher


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    redis: Redis | None = None,
    launcher: RunLauncher | None = None,
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
    for router in (
        catalog_router,
        runs_router,
        events_router,
        health_router,
    ):
        application.include_router(router, prefix=API_PREFIX)
    return application


app = create_app()
