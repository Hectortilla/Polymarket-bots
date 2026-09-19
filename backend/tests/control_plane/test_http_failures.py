"""HTTP and subscription cleanup when required services fail."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from api.auth.passwords import PasswordVerificationError
from api.events.live.metrics import LiveMetrics
from api.http.errors import SERVICE_UNAVAILABLE_DETAIL
from api.http.middleware.private_cache import PrivateResponseMiddleware
from api.http.middleware.service_failures import ServiceFailureMiddleware
from api.http.protocol import CACHE_CONTROL_HEADER, NO_STORE_CACHE_DIRECTIVE
from api.http.sse.subscriptions import SubscriptionLane
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
        asyncio.run(app({"type": "http", "path": "/"}, AsyncMock(), send))
    assert raised.value.__suppress_context__
    send.assert_awaited_once()
    assert send.call_args.args[0]["headers"] == [
        (CACHE_CONTROL_HEADER.lower().encode(), NO_STORE_CACHE_DIRECTIVE.encode())
    ]


def test_subscription_failure_closes_transport_and_recovers():
    async def scenario():
        failed, ready = AsyncMock(), AsyncMock()
        failed.subscribe.side_effect = RedisError("private detail")

        async def receive(**kwargs):
            await asyncio.sleep(0.01)
            return {"type": "subscribe", "channel": b"channel", "data": 1}

        ready.get_message.side_effect = receive
        redis = Mock()
        redis.pubsub.side_effect = [failed, ready]
        lane = SubscriptionLane(redis, lambda _: None, lambda: None, LiveMetrics())
        lane.add("channel")
        lane.start()
        await lane.ready("channel")
        await lane.close()
        failed.aclose.assert_awaited_once()
        ready.aclose.assert_awaited_once()

    asyncio.run(scenario())


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
