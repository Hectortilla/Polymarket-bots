"""Incident race/failure acceptance against disposable PostgreSQL and Redis."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from api.auth.models import UserRow
from api.auth.store import AuthStore
from api.events.contracts import LiveStreamHealthEvent
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.limits.errors import ResourceLimitError
from api.operations.alerts.policy import (
    DATABASE_SIZE_ALERT_BYTES,
    QUEUE_AGE_ALERT_SECONDS,
)
from api.operations.control import OperatorControl
from api.operations.measurement_contracts import DatabaseMeasurements
from api.operations.measurements import OperationMeasurements
from api.operations.models import OperationControlRow, OperatorAuditRow
from api.operations.monitor import OperationMonitor
from api.operations.observations.contracts import AlertCode, Observation
from api.operations.observations.sink import OPERATION_LOG, OPERATION_LOGGER_NAME
from api.operations.schema import OperatorAction, OperatorOutcome
from api.operations.telemetry.presence import WorkerPresenceStore
from api.runs.failures import ExecutionOwnershipLost
from api.runs.lease import ExecutionLease
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from polybot.cli.observability.events import StreamHealth
from polybot.framework.clock import system_now_utc
from sqlalchemy import delete, select, update

from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services

ACTOR = "disposable-test-operator"


def test_suspend_fences_active_run_revokes_access_and_preserves_history(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            claimed = await claim_run(sessions, run)
            async with sessions() as session:
                account = await AuthStore(session).find_user(user.email, lock=True)
                token = await AuthStore(session).issue_session(account, None)
            async with sessions() as session:
                assert (
                    await OperatorControl(session, ACTOR).apply(
                        OperatorAction.SUSPEND, user.id
                    )
                    is OperatorOutcome.APPLIED
                )
                assert await AuthStore(session).current_user(token) is None
                assert (
                    await RunStore(session).read(run.id)
                ).status is RunStatus.INTERRUPTED
                assert len(await EventStore(session).read(run.id)) == 1
                with pytest.raises(ExecutionOwnershipLost):
                    await ExecutionLease(claimed.execution_token).require(
                        session, run.id
                    )
            with pytest.raises(ResourceLimitError):
                await queue_run(sessions, bot)
            async with sessions() as session:
                assert (
                    await OperatorControl(session, ACTOR).apply(
                        OperatorAction.SUSPEND, user.id
                    )
                    is OperatorOutcome.UNCHANGED
                )
                assert len(await EventStore(session).read(run.id)) == 1
                await OperatorControl(session, ACTOR).apply(
                    OperatorAction.RESUME_ACCOUNT, user.id
                )
                assert await AuthStore(session).current_user(token) is None
            assert (await queue_run(sessions, bot)).id != run.id

    asyncio.run(scenario())


def test_global_stop_serializes_with_launch_and_resume_never_restarts(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)

            async def stop():
                async with sessions() as session:
                    await OperatorControl(session, ACTOR).apply(OperatorAction.STOP_ALL)

            async def launch():
                try:
                    return await queue_run(sessions, bot)
                except ResourceLimitError:
                    return None

            run, _ = await asyncio.gather(launch(), stop())
            async with sessions() as session:
                if run is not None:
                    assert (
                        await RunStore(session).read(run.id)
                    ).status is RunStatus.STOPPED
                await OperatorControl(session, ACTOR).apply(OperatorAction.STOP_ALL)
                await OperatorControl(session, ACTOR).apply(
                    OperatorAction.RESUME_ADMISSIONS
                )
                if run is not None:
                    assert (
                        await RunStore(session).claim(run.id, now=system_now_utc())
                        is None
                    )
            await queue_run(sessions, bot)

    asyncio.run(scenario())


def test_operator_audit_and_termination_rollback_together(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                with patch.object(
                    session, "commit", AsyncMock(side_effect=RuntimeError("secret"))
                ):
                    with pytest.raises(RuntimeError):
                        await OperatorControl(session, ACTOR).apply(
                            OperatorAction.SUSPEND, user.id
                        )
            async with sessions() as session:
                assert (await session.get(UserRow, user.id)).suspended_at is None
                assert (await RunStore(session).read(run.id)).status is RunStatus.QUEUED
                assert list(await session.scalars(select(OperatorAuditRow))) == []
                assert await EventStore(session).read(run.id) == ()
                await OperatorControl(session, ACTOR).apply(
                    OperatorAction.STOP_RUN, run.id
                )
                assert (
                    await OperatorControl(session, ACTOR).apply(
                        OperatorAction.STOP_RUN, run.id
                    )
                    is OperatorOutcome.UNCHANGED
                )
                assert (
                    await OperatorControl(session, ACTOR).apply(
                        OperatorAction.STOP_RUN, uuid4()
                    )
                    is OperatorOutcome.NOT_FOUND
                )
                audits = list(await session.scalars(select(OperatorAuditRow)))
                assert len(audits) == 3
                assert all(audit.actor == ACTOR for audit in audits)

    asyncio.run(scenario())


def test_required_control_cannot_disappear_into_permissive_admission(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            async with sessions() as session:
                await session.execute(delete(OperationControlRow))
                await session.commit()
            with pytest.raises(RuntimeError, match="required operation control"):
                await queue_run(sessions, bot)

    asyncio.run(scenario())


def test_monitor_injected_failures_are_actionable_and_redacted(limits_services, caplog):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            monitor = OperationMonitor(
                sessions, redis, lease_seconds=DEFAULT_LEASE_SECONDS
            )
            async with sessions() as session:
                await session.execute(
                    update(RunRow)
                    .where(RunRow.id == run.id)
                    .values(
                        created_at=system_now_utc()
                        - timedelta(seconds=QUEUE_AGE_ALERT_SECONDS + 1)
                    )
                )
                await session.commit()
            alerts = await monitor.tick()
            assert AlertCode.WORKER_UNAVAILABLE in alerts
            assert AlertCode.QUEUE_DELAY in alerts
            claimed = await claim_run(sessions, run)
            telemetry = WorkerPresenceStore(redis)
            worker = uuid4()
            await telemetry.refresh(worker)
            writer = RunEventWriter(sessions, redis).for_execution(
                claimed.execution_token, DEFAULT_LEASE_SECONDS
            )
            await writer.health_writer().record(
                LiveStreamHealthEvent.from_observation(
                    run.id, StreamHealth(0, 0, 0, True), occurred_at=system_now_utc()
                )
            )
            assert AlertCode.FEED_DEGRADED in await monitor.tick()
            with patch.object(
                OperationMeasurements,
                "read",
                AsyncMock(
                    return_value=DatabaseMeasurements(
                        0, 0, 1, DATABASE_SIZE_ALERT_BYTES, (), False
                    )
                ),
            ):
                alerts = await monitor.tick()
                assert (
                    AlertCode.STORAGE_GROWTH in alerts and AlertCode.STUCK_RUN in alerts
                )
            with (
                patch.object(
                    OperationMeasurements,
                    "read",
                    AsyncMock(side_effect=RuntimeError("private-password")),
                ),
                patch.object(
                    WorkerPresenceStore,
                    "count",
                    AsyncMock(side_effect=RuntimeError("private-token")),
                ),
                patch(
                    "api.operations.monitor.probes.shutil.disk_usage",
                    side_effect=OSError("private-path"),
                ),
            ):
                alerts = await monitor.tick()
                assert set(alerts) == {
                    AlertCode.DATABASE_UNAVAILABLE,
                    AlertCode.REDIS_UNAVAILABLE,
                    AlertCode.STORAGE_UNAVAILABLE,
                }
            await asyncio.to_thread(OPERATION_LOG.flush)
            records = [
                json.loads(record.message)
                for record in caplog.records
                if record.name == OPERATION_LOGGER_NAME
            ]
            assert any(
                record["event"] == Observation.ALERT
                and record["owner"]
                and record["response"]
                for record in records
            )
            assert (
                "private-password" not in caplog.text
                and "private-token" not in caplog.text
                and "private-path" not in caplog.text
            )
            await telemetry.remove(worker)

    asyncio.run(scenario())
