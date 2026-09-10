"""HTTP admission, allowance responses and private usage endpoint."""

from collections.abc import AsyncIterator
from http import HTTPMethod
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from api.auth.dependencies import CurrentUserDependency
from api.auth.policy import PUBLIC_ROUTES
from api.http.dependencies import RedisDependency, SessionFactoryDependency
from api.http.protocol import RETRY_AFTER_HEADER
from api.http.routes.paths import (
    GRAPH_PREVIEW_PATH,
    MARKET_LOOKUP_PATH,
    MARKET_SEARCH_PATH,
    READ_USAGE_OPERATION_ID,
    USAGE_PATH,
    api_route_path,
)
from api.http.routes.run_lookup import require_stored_run
from api.limits.contracts import AccountUsage
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.limits.policy import RATE_WINDOW_SECONDS
from api.limits.redis.request_budgets import RequestRateLimiter
from api.limits.redis.stream_admission import OpenStreamAdmission, StreamLease
from api.limits.usage import AccountUsageReader
from api.operations.http import ADMISSION_REJECTION_SCOPE_KEY

EXPENSIVE_MUTATION_METHODS = frozenset({HTTPMethod.POST, HTTPMethod.PATCH})
EXPENSIVE_READ_PATHS = frozenset(
    map(api_route_path, (MARKET_SEARCH_PATH, MARKET_LOOKUP_PATH, GRAPH_PREVIEW_PATH))
)
RESOURCE_STATUS = {
    ResourceLimitCode.USER_ALLOWANCE: status.HTTP_429_TOO_MANY_REQUESTS,
    ResourceLimitCode.GLOBAL_CAPACITY: status.HTTP_503_SERVICE_UNAVAILABLE,
    ResourceLimitCode.INCIDENT_PAUSED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ResourceLimitCode.ACCOUNT_SUSPENDED: status.HTTP_403_FORBIDDEN,
    ResourceLimitCode.INVALID_CONFIGURATION: status.HTTP_422_UNPROCESSABLE_CONTENT,
}
router = APIRouter()


async def application_resource_limits(request: Request) -> None:
    if (request.method, request.url.path) in PUBLIC_ROUTES:
        return
    await RequestRateLimiter(
        request.app.state.redis, request.state.user.id
    ).consume_request_budget(
        expensive=request.method in EXPENSIVE_MUTATION_METHODS
        or request.url.path in EXPENSIVE_READ_PATHS,
    )


async def resource_limit_response(
    request: Request, error: ResourceLimitError
) -> JSONResponse:
    request.scope[ADMISSION_REJECTION_SCOPE_KEY] = True
    headers = (
        {}
        if error.code in {ResourceLimitCode.INVALID_CONFIGURATION, ResourceLimitCode.ACCOUNT_SUSPENDED}
        else {RETRY_AFTER_HEADER: str(RATE_WINDOW_SECONDS)}
    )
    return JSONResponse(
        status_code=RESOURCE_STATUS[error.code],
        content={"detail": error.detail, "code": error.code.value},
        headers=headers,
    )


@router.get(
    USAGE_PATH, response_model=AccountUsage, operation_id=READ_USAGE_OPERATION_ID
)
async def read_usage(
    session_factory: SessionFactoryDependency, user: CurrentUserDependency
) -> AccountUsage:
    async with session_factory() as session:
        return await AccountUsageReader(session, user.id).usage()


async def stream_lease(
    run_id: UUID,
    user: CurrentUserDependency,
    redis: RedisDependency,
    session_factory: SessionFactoryDependency,
) -> AsyncIterator[StreamLease]:
    async with session_factory() as session:
        await require_stored_run(session, run_id, user.id)
    lease = await OpenStreamAdmission(redis, user.id).acquire_stream()
    try:
        yield lease
    finally:
        await lease.release()


StreamLeaseDependency = Annotated[StreamLease, Depends(stream_lease, scope="request")]
