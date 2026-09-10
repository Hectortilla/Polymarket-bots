"""Concurrency acceptance at the operation, account and health-write boundaries."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from api.catalog.definitions import WINNER_DEFINITION_ID
from api.events.contracts import LiveStreamHealthEvent
from api.events.health.store import FeedHealthStore
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.http.protocol import RETRY_AFTER_HEADER
from api.http.routes.paths import BOTS_PATH, api_route_path
from api.limits.admission import RunAdmission
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.operations.control import OperatorControl
from api.operations.models import OperatorAuditRow
from api.operations.schema import OperatorAction, OperatorOutcome
from api.runs.failures import ExecutionOwnershipLost
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from fastapi import status
from httpx import ASGITransport, AsyncClient
from polybot.cli.observability.events import StreamHealth
from polybot.framework.clock import system_now_utc
from sqlalchemy import func, select, update

from control_plane.auth_fixtures import TEST_HEADERS, TEST_ORIGIN
from control_plane.limits_fixtures import (
    account_app,
    account_bot,
    claim_run,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services

ACTOR = "fence-test-operator"


@pytest.mark.parametrize("launch_first", [True, False])
def test_launch_and_suspension_serialize_in_both_orders(limits_services, launch_first):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            locked, release = asyncio.Event(), asyncio.Event()
            original_lock = RunAdmission.lock_transaction
            first_lock = True

            async def gate(self):
                nonlocal first_lock
                await original_lock(self)
                if first_lock:
                    first_lock = False
                    locked.set()
                    await release.wait()

            async def suspend():
                async with sessions() as session:
                    return await OperatorControl(session, ACTOR).apply(
                        OperatorAction.SUSPEND, user.id
                    )

            with patch.object(RunAdmission, "lock_transaction", gate):
                first = asyncio.create_task(
                    queue_run(sessions, bot) if launch_first else suspend()
                )
                await locked.wait()
                second = asyncio.create_task(
                    suspend() if launch_first else queue_run(sessions, bot)
                )
                release.set()
                results = await asyncio.gather(first, second, return_exceptions=True)
            async with sessions() as session:
                runs = list(await session.scalars(select(RunRow)))
                if launch_first:
                    assert len(runs) == 1 and runs[0].status is RunStatus.STOPPED
                    assert len(await EventStore(session).read(runs[0].id)) == 1
                else:
                    assert runs == []
                    assert isinstance(results[1], ResourceLimitError)
                    assert results[1].code is ResourceLimitCode.ACCOUNT_SUSPENDED

    asyncio.run(scenario())


def test_global_stop_terminalizes_active_and_queued_runs_once(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, first_bot = await account_bot(sessions)
            _, second_bot = await account_bot(sessions)
            active = await queue_run(sessions, first_bot)
            await claim_run(sessions, active)
            queued = await queue_run(sessions, second_bot)
            async with sessions() as session:
                operator = OperatorControl(session, ACTOR)
                assert (
                    await operator.apply(OperatorAction.STOP_ALL)
                    is OperatorOutcome.APPLIED
                )
                assert (
                    await operator.apply(OperatorAction.STOP_ALL)
                    is OperatorOutcome.UNCHANGED
                )
                for run, expected in [
                    (active, RunStatus.INTERRUPTED),
                    (queued, RunStatus.STOPPED),
                ]:
                    assert (await RunStore(session).read(run.id)).status is expected
                    assert len(await EventStore(session).read(run.id)) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("ownership", ["wrong", "expired", "terminal"])
def test_health_sink_refuses_lost_execution_ownership(limits_services, ownership):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            claimed = await claim_run(sessions, run)
            writer = RunEventWriter(sessions, redis).for_execution(
                claimed.execution_token, DEFAULT_LEASE_SECONDS
            )
            event = LiveStreamHealthEvent.from_observation(
                run.id, StreamHealth(0, 0, 0), occurred_at=system_now_utc()
            )
            await writer.health_writer().record(event)
            before = await redis.get(FeedHealthStore.key(run.id))
            if ownership == "wrong":
                writer = RunEventWriter(sessions, redis).for_execution(
                    uuid4(), DEFAULT_LEASE_SECONDS
                )
            else:
                async with sessions() as session:
                    if ownership == "terminal":
                        await OperatorControl(session, ACTOR).apply(
                            OperatorAction.STOP_RUN, run.id
                        )
                    else:
                        await session.execute(
                            update(RunRow)
                            .where(RunRow.id == run.id)
                            .values(
                                heartbeat_at=system_now_utc()
                                - timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)
                            )
                        )
                        await session.commit()
            with pytest.raises(ExecutionOwnershipLost):
                await writer.health_writer().record(event)
            assert await redis.get(FeedHealthStore.key(run.id)) == before

    asyncio.run(scenario())


def test_suspended_write_boundary_rejects_already_authenticated_bot_requests(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, _ = await account_bot(sessions)
            # Simulate identity already authenticated before suspension commits.
            app = account_app(sessions, redis, user)
            app.state.market_discovery = AsyncMock()
            async with sessions() as session:
                await OperatorControl(session, ACTOR).apply(
                    OperatorAction.SUSPEND, user.id
                )
            requests = [
                (
                    BOTS_PATH,
                    {
                        "definition_id": WINNER_DEFINITION_ID,
                        "inputs": {"name": "forbidden bot"},
                    },
                ),
            ]
            async with AsyncClient(
                transport=ASGITransport(app), base_url=TEST_ORIGIN, headers=TEST_HEADERS
            ) as client:
                for path, body in requests:
                    response = await client.post(api_route_path(path), json=body)
                    assert response.status_code == status.HTTP_403_FORBIDDEN
                    assert (
                        response.json()["code"] == ResourceLimitCode.ACCOUNT_SUSPENDED
                    )
                    assert RETRY_AFTER_HEADER not in response.headers

    asyncio.run(scenario())


def test_account_missing_and_repeated_resume_are_audited_without_run_changes(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                operator = OperatorControl(session, ACTOR)
                for action in (OperatorAction.SUSPEND, OperatorAction.RESUME_ACCOUNT):
                    assert (
                        await operator.apply(action, uuid4())
                        is OperatorOutcome.NOT_FOUND
                    )
                for _ in range(2):
                    assert (
                        await operator.apply(OperatorAction.RESUME_ACCOUNT, user.id)
                        is OperatorOutcome.UNCHANGED
                    )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(OperatorAuditRow)
                    )
                    == 4
                )
                assert (await RunStore(session).read(run.id)).status is RunStatus.QUEUED
                assert await EventStore(session).read(run.id) == ()

    asyncio.run(scenario())
