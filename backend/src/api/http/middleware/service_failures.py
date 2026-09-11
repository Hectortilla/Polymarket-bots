"""Secret-safe translation of required-service failures at the HTTP boundary."""

import logging

from fastapi import status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.auth.passwords import PasswordVerificationError
from api.http.errors import HTTP_ERROR_DETAIL_FIELD, SERVICE_UNAVAILABLE_DETAIL
from api.http.protocol import ASGI_HTTP_RESPONSE_START, ASGI_HTTP_SCOPE, ASGI_TYPE_FIELD

LOGGER = logging.getLogger(__name__)


class ServiceFailureMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope[ASGI_TYPE_FIELD] != ASGI_HTTP_SCOPE:
            await self.app(scope, receive, send)
            return
        response_started = False

        async def track_response_start(message: Message) -> None:
            nonlocal response_started
            if message[ASGI_TYPE_FIELD] == ASGI_HTTP_RESPONSE_START:
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response_start)
        except (SQLAlchemyError, RedisError, PasswordVerificationError, TimeoutError):
            LOGGER.error("request failed because a required service is unavailable")
            if response_started:
                # Headers are immutable once streaming begins; end the failed response.
                raise RuntimeError(SERVICE_UNAVAILABLE_DETAIL) from None
            await JSONResponse(
                {HTTP_ERROR_DETAIL_FIELD: SERVICE_UNAVAILABLE_DETAIL},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )(scope, receive, send)
