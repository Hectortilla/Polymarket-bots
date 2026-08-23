from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from polybot_control_plane.api.sse import (
    SSE_FIELD_SEPARATOR,
    SSE_ID_FIELD,
    stream_run_event_frames,
)
from polybot_control_plane.api.lifecycle import ApiRunLifecycle
from polybot_control_plane.api.routes.runs import RUN_LAUNCH_FAILURE_REASON
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    INITIAL_DEFINITION_VERSION,
    WINNER_DEFINITION_ID,
)
from polybot_control_plane.database import async_database_url
from polybot_control_plane.events.channels import (
    encode_durable_wake_frame,
    run_event_channel,
)
from polybot_control_plane.events.contracts import (
    RunLifecycleEvent,
    RunStatusPayload,
)
from polybot_control_plane.events.ids import FIRST_EVENT_CURSOR
from polybot_control_plane.events.store import EventStore
from polybot_control_plane.runs.status import RunStatus
from polybot_control_plane.runs.store import RunStore
from control_plane.service_config import (
    POSTGRES_AND_REDIS_NOT_CONFIGURED_SKIP_REASON,
    POSTGRES_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
    TEST_REDIS_URL_ENV,
)


@pytest.mark.postgres
def test_api_owned_terminal_transitions_store_one_event_atomically() -> None:
    postgres_url = os.getenv(TEST_POSTGRES_URL_ENV)
    if postgres_url is None:
        pytest.skip(POSTGRES_NOT_CONFIGURED_SKIP_REASON)
    database_url = async_database_url(postgres_url).render_as_string(
        hide_password=False
    )
    alembic = Config("alembic.ini")
    alembic.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(alembic, "base")
    command.upgrade(alembic, "head")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        config = CATALOG[WINNER_DEFINITION_ID].parse_config({"name": "stop"})
        launch_failure_detail = f"RuntimeError: {RUN_LAUNCH_FAILURE_REASON}"
        try:
            async with session_factory() as session:
                queued = await RunStore(session).create(
                    definition_id=WINNER_DEFINITION_ID,
                    definition_version=INITIAL_DEFINITION_VERSION,
                    config=config,
                )

            async def stop_queued_run():
                async with session_factory() as session:
                    return await ApiRunLifecycle(session).request_stop(
                        queued.id,
                        now=datetime.now(UTC),
                    )

            first, second = await asyncio.gather(
                stop_queued_run(),
                stop_queued_run(),
            )
            async with session_factory() as session:
                events = await EventStore(session).read(queued.id)

            assert first is not None and first[0].status is RunStatus.STOPPED
            assert second is not None and second[0].status is RunStatus.STOPPED
            assert sum(result[1] is not None for result in (first, second)) == 1
            assert len(events) == 1
            assert events[0].payload.status is RunStatus.STOPPED

            async with session_factory() as session:
                failed = await RunStore(session).create(
                    definition_id=WINNER_DEFINITION_ID,
                    definition_version=INITIAL_DEFINITION_VERSION,
                    config=config,
                )
                running = await RunStore(session).create(
                    definition_id=WINNER_DEFINITION_ID,
                    definition_version=INITIAL_DEFINITION_VERSION,
                    config=config,
                )
                rollback = await RunStore(session).create(
                    definition_id=WINNER_DEFINITION_ID,
                    definition_version=INITIAL_DEFINITION_VERSION,
                    config=config,
                )
                claimed = await RunStore(session).claim(
                    running.id,
                    now=datetime.now(UTC),
                )
                assert claimed is not None
                assert await RunStore(session).mark_running(running.id)

            async with session_factory() as session:
                stopped_running = await ApiRunLifecycle(session).request_stop(
                    running.id,
                    now=datetime.now(UTC),
                )
            async with session_factory() as session:
                failed_run, _ = await ApiRunLifecycle(session).fail_launch(
                    failed.id,
                    now=datetime.now(UTC),
                    failure_detail=launch_failure_detail,
                )
            async with session_factory() as session:
                failed_events = await EventStore(session).read(failed.id)
                running_events = await EventStore(session).read(running.id)

            assert stopped_running is not None
            assert stopped_running[0].status is RunStatus.STOP_REQUESTED
            assert stopped_running[1] is None
            assert running_events == ()
            assert failed_run.status is RunStatus.FAILED
            assert failed_run.failure_detail == launch_failure_detail
            assert len(failed_events) == 1
            assert failed_events[0].payload.status is RunStatus.FAILED

            async with session_factory() as session:
                with patch.object(
                    session,
                    "flush",
                    new=AsyncMock(side_effect=RuntimeError("flush failed")),
                ):
                    with pytest.raises(RuntimeError, match="flush failed"):
                        await ApiRunLifecycle(session).request_stop(
                            rollback.id,
                            now=datetime.now(UTC),
                        )
            async with session_factory() as session:
                rolled_back = await RunStore(session).read(rollback.id)
                rollback_events = await EventStore(session).read(rollback.id)
            assert rolled_back is not None
            assert rolled_back.status is RunStatus.QUEUED
            assert rollback_events == ()

            async with session_factory() as session:
                stopped_again = await ApiRunLifecycle(session).request_stop(
                    queued.id,
                    now=datetime.now(UTC),
                )
                stopped_events = await EventStore(session).read(queued.id)
            assert stopped_again is not None
            assert stopped_again[0].status is RunStatus.STOPPED
            assert stopped_again[1] is None
            assert len(stopped_events) == 1

            async with session_factory() as session:
                with pytest.raises(
                    RuntimeError,
                    match="queued launch failure transition was lost",
                ):
                    await ApiRunLifecycle(session).fail_launch(
                        failed.id,
                        now=datetime.now(UTC),
                        failure_detail="duplicate",
                    )
            async with session_factory() as session:
                assert (
                    await ApiRunLifecycle(session).request_stop(
                        uuid4(),
                        now=datetime.now(UTC),
                    )
                    is None
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic, "base")


@pytest.mark.postgres
def test_sse_handoff_rechecks_postgres_after_real_redis_subscribe() -> None:
    postgres_url = os.getenv(TEST_POSTGRES_URL_ENV)
    redis_url = os.getenv(TEST_REDIS_URL_ENV)
    if postgres_url is None or redis_url is None:
        pytest.skip(POSTGRES_AND_REDIS_NOT_CONFIGURED_SKIP_REASON)
    database_url = async_database_url(postgres_url).render_as_string(
        hide_password=False
    )
    alembic = Config("alembic.ini")
    alembic.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(alembic, "base")
    command.upgrade(alembic, "head")

    async def scenario() -> tuple[int, ...]:
        engine = create_async_engine(database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis.from_url(redis_url)
        config = CATALOG[WINNER_DEFINITION_ID].parse_config({"name": "sse"})
        try:
            async with session_factory() as session:
                run = await RunStore(session).create(
                    definition_id=WINNER_DEFINITION_ID,
                    definition_version=INITIAL_DEFINITION_VERSION,
                    config=config,
                )
                first = await EventStore(session).append(
                    _lifecycle_event(run.id, RunStatus.RUNNING)
                )

            async def inject_terminal_event() -> None:
                async with session_factory() as session:
                    terminal = await EventStore(session).append(
                        _lifecycle_event(run.id, RunStatus.STOPPED)
                    )
                await redis.publish(
                    run_event_channel(run.id),
                    encode_durable_wake_frame(terminal.id),
                )

            wrapped_redis = _InjectingRedis(redis, inject_terminal_event)
            frames = [
                frame
                async for frame in stream_run_event_frames(
                    run.id,
                    after_event_id=FIRST_EVENT_CURSOR,
                    request=_ConnectedRequest(),
                    session_factory=session_factory,
                    redis=wrapped_redis,
                )
            ]
            assert first.id is not None
            return tuple(_frame_id(frame) for frame in frames)
        finally:
            await redis.aclose()
            await engine.dispose()

    try:
        assert asyncio.run(scenario()) == (1, 2)
    finally:
        command.downgrade(alembic, "base")


def _lifecycle_event(run_id, status: RunStatus) -> RunLifecycleEvent:
    return RunLifecycleEvent(
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=RunStatusPayload(status=status),
    )


def _frame_id(frame: str) -> int:
    prefix = f"{SSE_ID_FIELD}{SSE_FIELD_SEPARATOR}"
    return int(frame.splitlines()[0].removeprefix(prefix))


class _InjectingRedis:
    def __init__(self, redis: Redis, inject) -> None:
        self.redis = redis
        self.inject = inject

    def pubsub(self) -> "_InjectingPubSub":
        return _InjectingPubSub(self.redis.pubsub(), self.inject)


class _InjectingPubSub:
    def __init__(self, pubsub, inject) -> None:
        self.pubsub = pubsub
        self.inject = inject

    async def subscribe(self, channel: str) -> None:
        await self.pubsub.subscribe(channel)
        await self.inject()

    async def get_message(self, **kwargs):
        return await self.pubsub.get_message(**kwargs)

    async def unsubscribe(self, channel: str) -> None:
        await self.pubsub.unsubscribe(channel)

    async def aclose(self) -> None:
        await self.pubsub.aclose()


class _ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False
