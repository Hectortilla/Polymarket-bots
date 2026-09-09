"""Stream capacity belongs to authorized requests and lasts through cleanup."""

import asyncio
from time import monotonic
from unittest.mock import AsyncMock
from uuid import uuid4

import api.limits.redis.stream_admission as admission
import pytest
from api.http.routes.paths import RUN_EVENTS_STREAM_PATH, api_route_path
from api.http.sse import RunEventStreamer
from api.limits.redis.contracts import ResourceBucket
from api.limits.redis.stream_admission import StreamLease
from api.limits.streams import LimitedStreamResponse
from fastapi import status
from httpx import ASGITransport, AsyncClient

from control_plane.auth_fixtures import TEST_ORIGIN
from control_plane.limits_fixtures import (
    account_app,
    account_bot,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services


@pytest.mark.parametrize("ending", ["complete", "expiry", "disconnect", "slow-send"])
def test_response_closes_source_for_every_termination(ending):
    async def scenario():
        closed = asyncio.Event()
        first = asyncio.Event()

        async def source():
            try:
                yield "first"
                if ending != "complete":
                    await asyncio.Event().wait()
            finally:
                closed.set()

        async def send(message):
            if message["type"] == "http.response.body" and message.get("more_body"):
                first.set()
                if ending == "slow-send":
                    await asyncio.Event().wait()

        async def receive():
            await first.wait()
            if ending != "disconnect":
                await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        lease = StreamLease(
            AsyncMock(), ("user", "global"), "token", monotonic() + 0.02
        )
        response = LimitedStreamResponse(
            source(), lease, media_type="text/event-stream"
        )
        await asyncio.wait_for(
            response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send),
            1,
        )
        assert closed.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("expires", [False, True])
def test_http_dependency_releases_both_leases(limits_services, monkeypatch, expires):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            closed = asyncio.Event()
            keys = ResourceBucket.STREAMS.keys(user.id)

            async def stream(self, cursor):
                try:
                    assert all([await redis.zcard(key) == 1 for key in keys])
                    yield "data: fixture\n\n"
                    if expires:
                        await asyncio.Event().wait()
                finally:
                    closed.set()

            monkeypatch.setattr(RunEventStreamer, "stream", stream)
            monkeypatch.setattr(admission, "STREAM_LIFETIME_SECONDS", 0.05)
            app = account_app(sessions, redis, user)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=TEST_ORIGIN
            ) as client:
                response = await client.get(
                    api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run.id)
                )
                assert response.status_code == status.HTTP_200_OK
            assert closed.is_set()
            assert all([await redis.zcard(key) == 0 for key in keys])
            lease = await admission.OpenStreamAdmission(redis, user.id).acquire_stream()
            await lease.release()

    asyncio.run(scenario())


def test_foreign_stream_does_not_reserve_capacity(limits_services, monkeypatch):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, _ = await account_bot(sessions)
            _, foreign_bot = await account_bot(sessions)
            run = await queue_run(sessions, foreign_bot)
            acquire = AsyncMock(side_effect=AssertionError("unauthorized reservation"))
            monkeypatch.setattr(
                admission.OpenStreamAdmission, "acquire_stream", acquire
            )
            async with AsyncClient(
                transport=ASGITransport(app=account_app(sessions, redis, user)),
                base_url=TEST_ORIGIN,
            ) as client:
                response = await client.get(
                    api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run.id)
                )
            assert response.status_code == status.HTTP_404_NOT_FOUND
            acquire.assert_not_called()

    asyncio.run(scenario())


def test_redis_latency_cannot_extend_lease_lifetime(monkeypatch):
    async def scenario():
        redis = AsyncMock()

        async def delayed_eval(*args):
            await asyncio.sleep(0.02)
            return 0

        redis.eval.side_effect = delayed_eval
        monkeypatch.setattr(admission, "STREAM_LIFETIME_SECONDS", 0.01)
        lease = await admission.OpenStreamAdmission(redis, uuid4()).acquire_stream()
        assert lease.monotonic_deadline_seconds < monotonic()

    asyncio.run(scenario())


def test_expired_redis_members_do_not_block_stream_admission(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            owner = uuid4()
            keys = ResourceBucket.STREAMS.keys(owner)
            now, _ = await redis.time()
            for key in keys:
                await redis.zadd(
                    key,
                    {
                        f"expired-{i}": now - 1
                        for i in range(admission.PAPER_BETA.global_open_streams)
                    },
                )
            lease = await admission.OpenStreamAdmission(redis, owner).acquire_stream()
            assert all([await redis.zcard(key) == 1 for key in keys])
            await lease.release()

    asyncio.run(scenario())


def test_response_start_timeout_closes_unstarted_source():
    async def scenario():
        async def source():
            yield "unreachable"

        content = source()

        async def blocked_send(message):
            await asyncio.Event().wait()

        response = LimitedStreamResponse(
            content,
            StreamLease(AsyncMock(), ("user", "global"), "lease", monotonic() + 0.01),
            media_type="text/event-stream",
        )
        with pytest.raises(TimeoutError):
            await response.stream_response(blocked_send)
        assert content.ag_frame is None

    asyncio.run(scenario())
