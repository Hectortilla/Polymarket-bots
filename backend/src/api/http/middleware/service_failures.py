"""Secret-safe translation of required-service failures at the HTTP boundary."""

import logging

from fastapi import status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.auth.passwords import PasswordVerificationError
from api.http.errors import SERVICE_UNAVAILABLE_DETAIL

LOGGER = logging.getLogger(__name__)


class ServiceFailureMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def track_response_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
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
                {"detail": SERVICE_UNAVAILABLE_DETAIL},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )(scope, receive, send)
