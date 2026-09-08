"""HTTP and subscription cleanup when required services fail."""

import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from api.auth.passwords import PasswordVerificationError
from api.http.errors import SERVICE_UNAVAILABLE_DETAIL
from api.http.middleware.private_cache import PrivateResponseMiddleware
from api.http.middleware.service_failures import ServiceFailureMiddleware
from api.http.protocol import CACHE_CONTROL_HEADER, NO_STORE_CACHE_DIRECTIVE
from api.http.sse.subscription import RunSubscription
from fastapi import status
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.parametrize(
    "error_type", [SQLAlchemyError, RedisError, PasswordVerificationError]
)
def test_service_failure_after_headers_ends_without_a_second_response(error_type):
    async def failing_app(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": status.HTTP_200_OK, "headers": []}
        )
        raise error_type("private service detail")

    send = AsyncMock()
    app = PrivateResponseMiddleware(ServiceFailureMiddleware(failing_app))
    with pytest.raises(RuntimeError, match=SERVICE_UNAVAILABLE_DETAIL) as raised:
        asyncio.run(app({"type": "http"}, AsyncMock(), send))
    assert raised.value.__suppress_context__
    send.assert_awaited_once()
    assert send.call_args.args[0]["headers"] == [
        (CACHE_CONTROL_HEADER.lower().encode(), NO_STORE_CACHE_DIRECTIVE.encode())
    ]


@pytest.mark.parametrize("operation", ["subscribe", "unsubscribe"])
def test_subscription_failure_still_closes_the_owned_pubsub(operation):
    pubsub = AsyncMock()
    error = RedisError("subscription unavailable")
    getattr(pubsub, operation).side_effect = error
    redis = Mock()
    redis.pubsub.return_value = pubsub

    async def scenario():
        async with RunSubscription(redis, uuid4()):
            assert operation == "unsubscribe"

    with pytest.raises(RedisError) as raised:
        asyncio.run(scenario())
    assert raised.value is error
    pubsub.aclose.assert_awaited_once()


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_service_failure_preserves_non_http_protocols(scope_type):
    error = RedisError("service transport unavailable")
    inner = AsyncMock(side_effect=error)
    receive, send = AsyncMock(), AsyncMock()
    scope = {"type": scope_type}
    with pytest.raises(RedisError) as raised:
        asyncio.run(ServiceFailureMiddleware(inner)(scope, receive, send))
    assert raised.value is error
    inner.assert_awaited_once_with(scope, receive, send)
    send.assert_not_awaited()
