"""FastAPI application assembly for the private paper-run control plane."""

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from polybot.polymarket.discovery import MarketDiscovery
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.config import AuthSettings
from api.auth.dependencies import application_authentication
from api.auth.middleware import AuthBoundaryMiddleware
from api.auth.responses import AUTH_REQUIRED_RESPONSES
from api.auth.routes import router as auth_router
from api.auth.validation import safe_validation_error
from api.limits.errors import ResourceLimitError
from api.limits.http import (
    application_resource_limits,
    resource_limit_response,
    router as limits_router,
)
from api.execution.launcher import RunLauncher
from api.http.dependencies import application_lifespan
from api.http.middleware.private_cache import PrivateResponseMiddleware
from api.http.middleware.service_failures import ServiceFailureMiddleware
from api.http.routes.bots import router as bots_router
from api.http.routes.catalog import router as catalog_router
from api.http.routes.events import router as events_router
from api.http.routes.graph_preview import (
    router as graph_preview_router,
)
from api.http.routes.graph_templates import (
    router as graph_templates_router,
)
from api.http.routes.health import router as health_router
from api.http.routes.markets import router as markets_router
from api.http.routes.paths import API_PREFIX
from api.http.routes.runs import router as runs_router


def create_app(
    *,
    auth_settings: AuthSettings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    redis: Redis | None = None,
    launcher: RunLauncher | None = None,
    market_discovery: MarketDiscovery | None = None,
) -> FastAPI:
    application = FastAPI(
        title="Polybot Control Plane",
        dependencies=[
            Depends(application_authentication),
            Depends(application_resource_limits),
        ],
        responses=AUTH_REQUIRED_RESPONSES,
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=application_lifespan,
    )
    application.add_middleware(AuthBoundaryMiddleware)
    application.add_middleware(ServiceFailureMiddleware)
    # Keep cache protection outside errors so generated 503 responses are private too.
    application.add_middleware(PrivateResponseMiddleware)
    application.add_exception_handler(RequestValidationError, safe_validation_error)
    application.add_exception_handler(ResourceLimitError, resource_limit_response)
    if auth_settings is not None:
        application.state.auth_settings = auth_settings
    if session_factory is not None:
        application.state.session_factory = session_factory
    if redis is not None:
        application.state.redis = redis
    if launcher is not None:
        application.state.launcher = launcher
    if market_discovery is not None:
        application.state.market_discovery = market_discovery
    for router in (
        auth_router,
        limits_router,
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
