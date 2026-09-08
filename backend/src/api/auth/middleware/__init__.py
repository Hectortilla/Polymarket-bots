"""Credential ingress orchestration over CSRF, quota, and bounded-body guards."""

from http import HTTPMethod

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api.auth.middleware.body import AuthRequestBody
from api.auth.middleware.csrf import require_same_origin_json
from api.auth.policy import AUTH_ATTEMPT_LIMITS, RATE_LIMIT_DETAIL
from api.auth.throttle import AuthRateLimiter
from api.http.protocol import RETRY_AFTER_HEADER


class AuthBoundaryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            require_same_origin_json(request)
            attempt_limit = AUTH_ATTEMPT_LIMITS.get(request.url.path)
            if request.method == HTTPMethod.POST and attempt_limit is not None:
                # ASGI client addresses inherit Uvicorn's configured proxy trust.
                address = request.client.host if request.client else "unknown"
                allowed, retry_after = await AuthRateLimiter(
                    request.app.state.redis
                ).check(request.url.path, address, attempt_limit)
                if not allowed:
                    raise HTTPException(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        RATE_LIMIT_DETAIL,
                        headers={RETRY_AFTER_HEADER: str(retry_after)},
                    )
                body = await AuthRequestBody.read(receive)
                if body is None:
                    return
                receive = body.receive
        except HTTPException as error:
            await JSONResponse(
                {"detail": error.detail},
                status_code=error.status_code,
                headers=error.headers,
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)
