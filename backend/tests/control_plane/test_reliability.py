"""Failure injection against the real durable run/lease accounting boundary."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from api.bots.store import BotStore
from api.events.contracts import LiveStreamHealthEvent, RunLifecycleEvent
from api.events.kinds import EventKind
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.execution.recovery import RunRecovery
from api.execution.recovery.policy import DELIVERY_RETRY_SECONDS
from api.http.lifecycle import ApiRunLifecycle
from api.http.protocol import IDEMPOTENCY_KEY_HEADER
from api.http.routes.paths import BOT_RUNS_PATH, api_route_path
from api.runs.failures import INTERRUPTION_DETAIL, ExecutionOwnershipLost
from api.runs.lease import ExecutionLease
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from httpx import ASGITransport, AsyncClient
from polybot.cli.observability.events import StreamHealth
from polybot.framework.clock import system_now_utc
from sqlalchemy import func, select, update

from control_plane.auth_fixtures import TEST_HEADERS
from control_plane.limits_fixtures import (
    account_app,
    account_bot,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services


def test_concurrent_launch_retry_preserves_one_snapshot_and_reservation(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            key = uuid4()

            async def launch():
                async with sessions() as session:
                    return await RunStore(session).create_from_bot(bot, launch_key=key)

            first, retry = await asyncio.gather(launch(), launch())
            assert first.id == retry.id
            async with sessions() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(RunRow)) == 1
                )
                await RunStore(session).request_stop(first.id, now=system_now_utc())
            assert (await launch()).status is RunStatus.STOPPED
            async with sessions() as session:
                deliberate = await RunStore(session).create_from_bot(
                    bot, launch_key=uuid4()
                )
            assert deliberate.id != first.id

    asyncio.run(scenario())


def test_recovery_delivers_after_api_death_and_retries_redis_outage(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(
                sessions, bot
            )  # API dies after commit, before enqueue.
            launcher = AsyncMock()
            launcher.launch.side_effect = ConnectionError("redis unavailable")
            recovery = RunRecovery(
                sessions, launcher, lease_seconds=DEFAULT_LEASE_SECONDS
            )
            await recovery.tick()
            async with sessions() as session:
                assert (await RunStore(session).read(run.id)).status is RunStatus.QUEUED
                assert await EventStore(session).read(run.id) == ()
                await session.execute(update(RunRow).values(delivery_attempted_at=None))
                await session.commit()
            launcher.launch.side_effect = None
            await asyncio.gather(recovery.tick(), recovery.tick())
            assert launcher.launch.await_count == 2

            async def claim():
                async with sessions() as session:
                    return await RunStore(session).claim(run.id, now=system_now_utc())

            assert (
                sum(
                    result is not None
                    for result in await asyncio.gather(claim(), claim())
                )
                == 1
            )

    asyncio.run(scenario())


def test_expired_worker_cannot_renew_or_publish_and_recovery_is_atomic(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                claimed = await RunStore(session).claim(run.id, now=system_now_utc())
            writer = RunEventWriter(sessions, redis).for_execution(
                claimed.execution_token, DEFAULT_LEASE_SECONDS
            )
            event = RunLifecycleEvent.from_terminal_status(
                run.id, RunStatus.STOPPED, occurred_at=system_now_utc()
            )
            async with sessions() as session:
                await session.execute(
                    update(RunRow)
                    .where(RunRow.id == run.id)
                    .values(
                        heartbeat_at=system_now_utc()
                        - timedelta(seconds=DEFAULT_LEASE_SECONDS * 2)
                    )
                )
                await session.commit()
                owned = RunStore(session).owned_by(
                    ExecutionLease(claimed.execution_token)
                )
                assert not await owned.heartbeat(run.id, now=system_now_utc())
                assert not await owned.mark_running(run.id)
            with pytest.raises(ExecutionOwnershipLost):
                await writer.append(event)
            recovery = RunRecovery(
                sessions, AsyncMock(), lease_seconds=DEFAULT_LEASE_SECONDS
            )
            await asyncio.gather(recovery.tick(), recovery.tick())
            async with sessions() as session:
                restored = await RunStore(session).read(run.id)
                events = await EventStore(session).read(run.id)
                assert restored.status is RunStatus.INTERRUPTED
                assert restored.failure_detail == INTERRUPTION_DETAIL
                assert len(events) == 1
                assert events[0].payload.status is RunStatus.INTERRUPTED
                assert events[0].occurred_at == restored.ended_at
                assert (
                    await RunStore(session).claim(run.id, now=system_now_utc()) is None
                )
            with pytest.raises(ExecutionOwnershipLost):
                await writer.append(event)
            replacement = await queue_run(sessions, bot)
            async with sessions() as session:
                assert (
                    await RunStore(session).claim(replacement.id, now=system_now_utc())
                    is not None
                )

    asyncio.run(scenario())


def test_terminal_event_database_failure_rolls_back_state_and_reservation(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                await RunStore(session).claim(run.id, now=system_now_utc())
            async with sessions() as session:
                with patch.object(
                    session,
                    "flush",
                    new=AsyncMock(side_effect=ConnectionError("database outage")),
                ):
                    with pytest.raises(ConnectionError):
                        await RunStore(session).finish(
                            run.id, status=RunStatus.INTERRUPTED, now=system_now_utc()
                        )
            async with sessions() as session:
                assert (
                    await RunStore(session).read(run.id)
                ).status is RunStatus.STARTING
                assert await EventStore(session).read(run.id) == ()
                await RunStore(session).finish(
                    run.id, status=RunStatus.INTERRUPTED, now=system_now_utc()
                )
                assert len(await EventStore(session).read(run.id)) == 1

    asyncio.run(scenario())


def test_stop_reconciliation_race_converges_and_preserves_committed_history(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                await RunStore(session).claim(
                    run.id,
                    now=system_now_utc() - timedelta(seconds=DEFAULT_LEASE_SECONDS * 2),
                )

            async def stop():
                async with sessions() as session:
                    await ApiRunLifecycle(session).request_stop(
                        run.id, now=system_now_utc()
                    )

            recovery = RunRecovery(
                sessions, AsyncMock(), lease_seconds=DEFAULT_LEASE_SECONDS
            )
            await asyncio.gather(stop(), recovery.tick(), recovery.tick())
            async with sessions() as session:
                assert (
                    await RunStore(session).read(run.id)
                ).status is RunStatus.INTERRUPTED
                events = await EventStore(session).read(run.id)
                assert len(events) == 1
                assert events[0].kind is EventKind.RUN_LIFECYCLE

    asyncio.run(scenario())


def test_owned_http_launch_retries_after_lost_response_and_bot_edit(limits_services):

    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            other, _ = await account_bot(sessions)
            app = account_app(sessions, redis, user)
            headers = {IDEMPOTENCY_KEY_HEADER: str(uuid4())}
            route = api_route_path(BOT_RUNS_PATH, bot_id=bot.id)
            async with AsyncClient(
                transport=ASGITransport(app),
                base_url="http://test",
                headers=TEST_HEADERS,
            ) as client:
                original, retry = await asyncio.gather(
                    client.post(route, headers=headers),
                    client.post(route, headers=headers),
                )
                assert original.status_code == retry.status_code == 202
                assert original.json()["id"] == retry.json()["id"]
                app.state.launcher.launch.assert_awaited_once()
                async with sessions() as session:
                    await BotStore(session, user.id).update_config(
                        bot.id,
                        bot.config.model_copy(
                            update={"name": "edited after uncertain launch"}
                        ),
                    )
                    await RunStore(session).request_stop(
                        original.json()["id"], now=system_now_utc()
                    )
                recovered = await client.post(route, headers=headers)
                assert recovered.json()["status"] == RunStatus.STOPPED
                assert recovered.json()["config"] == original.json()["config"]
                assert recovered.json()["id"] == original.json()["id"]
                deliberate = await client.post(
                    route, headers={IDEMPOTENCY_KEY_HEADER: str(uuid4())}
                )
                assert deliberate.json()["id"] != original.json()["id"]
                assert (
                    await client.post(
                        route, headers={IDEMPOTENCY_KEY_HEADER: "malformed"}
                    )
                ).status_code == 422
            async with AsyncClient(
                transport=ASGITransport(account_app(sessions, redis, other)),
                base_url="http://test",
                headers=TEST_HEADERS,
            ) as client:
                assert (await client.post(route, headers=headers)).status_code == 404

    asyncio.run(scenario())


def test_live_fence_and_delivery_age_boundaries(limits_services):

    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            launcher = AsyncMock()
            recovery = RunRecovery(
                sessions, launcher, lease_seconds=DEFAULT_LEASE_SECONDS
            )
            await recovery.tick()
            await recovery.tick()
            launcher.launch.assert_awaited_once()
            async with sessions() as session:
                await session.execute(
                    update(RunRow)
                    .where(RunRow.id == run.id)
                    .values(
                        delivery_attempted_at=system_now_utc()
                        - timedelta(seconds=DELIVERY_RETRY_SECONDS * 2)
                    )
                )
                await session.commit()
            await recovery.tick()
            assert launcher.launch.await_count == 2
            async with sessions() as session:
                claimed = await RunStore(session).claim(run.id, now=system_now_utc())
            publisher = AsyncMock()
            live = LiveStreamHealthEvent.from_observation(
                run.id,
                StreamHealth(1, 2, 3, False, 1.0, 4, 1),
                occurred_at=system_now_utc(),
            )
            wrong = RunEventWriter(sessions, publisher).for_execution(
                uuid4(), DEFAULT_LEASE_SECONDS
            )
            with pytest.raises(ExecutionOwnershipLost):
                await wrong.publish_live(live)
            async with sessions() as session:
                await session.execute(
                    update(RunRow)
                    .where(RunRow.id == run.id)
                    .values(
                        heartbeat_at=system_now_utc()
                        - timedelta(seconds=DEFAULT_LEASE_SECONDS * 2)
                    )
                )
                await session.commit()
            expired = RunEventWriter(sessions, publisher).for_execution(
                claimed.execution_token, DEFAULT_LEASE_SECONDS
            )
            with pytest.raises(ExecutionOwnershipLost):
                await expired.publish_live(live)
            publisher.publish.assert_not_awaited()

    asyncio.run(scenario())
