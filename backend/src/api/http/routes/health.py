"""Control-plane dependency readiness endpoint."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from api.http.contracts import HealthResponse
from api.http.dependencies import (
    RedisDependency,
    SessionFactoryDependency,
)
from api.http.responses import SERVICE_UNAVAILABLE_RESPONSE
from api.http.routes.paths import HEALTH_OPERATION_ID, HEALTH_PATH

SERVICE_UNAVAILABLE_DETAIL = "service unavailable"

router = APIRouter()


@router.get(
    HEALTH_PATH,
    response_model=HealthResponse,
    operation_id=HEALTH_OPERATION_ID,
    responses=SERVICE_UNAVAILABLE_RESPONSE,
)
async def health(
    session_factory: SessionFactoryDependency,
    redis: RedisDependency,
) -> HealthResponse:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        if not await redis.ping():
            raise RuntimeError("Redis PING returned false")
    except Exception as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            SERVICE_UNAVAILABLE_DETAIL,
        ) from error
    return HealthResponse()
