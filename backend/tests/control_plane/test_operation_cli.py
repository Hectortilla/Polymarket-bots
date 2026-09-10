"""Exercise the private operator entrypoint with real disposable persistence."""

import asyncio
import json
import os
import pwd
import subprocess
import sys
from uuid import uuid4

import pytest
from api.database import DATABASE_URL_ENV
from api.deployment.settings import (
    ENVIRONMENT_ENV,
    Environment,
    StartupSettings,
)
from api.execution.config import REDIS_URL_ENV
from api.operations.__main__ import OPERATION_FAILED_DETAIL
from api.operations.commands import ReadCommand
from api.operations.contracts import RunInspection
from api.operations.models import OperationControlRow, OperatorAuditRow
from api.operations.monitor import OperationMonitor
from api.operations.observations.contracts import AlertCode
from api.operations.schema import (
    AUDIT_ACTION_CONSTRAINT,
    AUDIT_OUTCOME_CONSTRAINT,
    AUDIT_TABLE,
    CONTROL_TABLE,
    OperatorAction,
    OperatorOutcome,
)
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.status import RunStatus
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import StatementError

from control_plane.limits_fixtures import account_bot, queue_run, resource_services
from control_plane.limits_fixtures import limits_services as limits_services


class OperatorCommandClient:
    def __init__(self, settings):
        self.env = {
            **os.environ,
            DATABASE_URL_ENV: settings[0],
            REDIS_URL_ENV: settings[1],
            ENVIRONMENT_ENV: Environment.DEVELOPMENT,
        }

    def run(self, command, target=None):
        args = [sys.executable, "-m", "api.operations", str(command)]
        if target is not None:
            args.append(str(target))
        return subprocess.run(
            args, env=self.env, capture_output=True, text=True, timeout=20
        )


def test_cli_inspection_stop_retry_and_unknown_targets(limits_services):
    async def seed():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            return user, await queue_run(sessions, bot)

    user, run = asyncio.run(seed())
    client = OperatorCommandClient(limits_services)
    inspection = client.run(ReadCommand.INSPECT_RUN, run.id)
    assert inspection.returncode == 0
    payload = json.loads(inspection.stdout)
    assert set(payload) == set(RunInspection.model_fields)
    assert payload["owner_user_id"] == str(user.id)
    assert (
        user.email not in inspection.stdout
        and user.password_hash not in inspection.stdout
    )
    assert json.loads(client.run(ReadCommand.LIST_RUNS).stdout)["runs"][0]["id"] == str(
        run.id
    )
    first = client.run(OperatorAction.STOP_RUN, run.id)
    retry = client.run(OperatorAction.STOP_RUN, run.id)
    assert first.returncode == retry.returncode == 0
    assert json.loads(first.stdout)["outcome"] == OperatorOutcome.APPLIED
    assert json.loads(retry.stdout)["outcome"] == OperatorOutcome.UNCHANGED
    assert (
        json.loads(client.run(ReadCommand.INSPECT_RUN, run.id).stdout)["status"]
        == RunStatus.STOPPED
    )

    async def check_actor():
        async with resource_services(limits_services) as (sessions, redis):
            async with sessions() as session:
                actors = list(await session.scalars(select(OperatorAuditRow.actor)))
                assert actors == [pwd.getpwuid(os.geteuid()).pw_name] * 2

    asyncio.run(check_actor())
    missing = client.run(ReadCommand.INSPECT_RUN, uuid4())
    assert missing.returncode != 0 and OPERATION_FAILED_DETAIL in missing.stderr
    for command, target in [
        (OperatorAction.STOP_RUN, None),
        (ReadCommand.STATUS, uuid4()),
        (ReadCommand.INSPECT_RUN, "invalid"),
        ("unrecognized", None),
    ]:
        assert client.run(command, target).returncode != 0


def test_status_reports_unknown_dependencies_and_missing_singleton(limits_services):
    async def remove_control():
        async with resource_services(limits_services) as (sessions, redis):
            async with sessions() as session:
                await session.execute(delete(OperationControlRow))
                await session.commit()
            alerts = await OperationMonitor(
                sessions, redis, lease_seconds=DEFAULT_LEASE_SECONDS
            ).tick()
            assert AlertCode.CONTROL_UNAVAILABLE in alerts

    asyncio.run(remove_control())
    client = OperatorCommandClient(limits_services)
    result = client.run(ReadCommand.STATUS)
    payload = json.loads(result.stdout)
    assert result.returncode != 0 and payload["healthy"] is False
    assert AlertCode.CONTROL_UNAVAILABLE in payload["alerts"]
    client.env[DATABASE_URL_ENV] = (
        "postgresql://test:private-secret@127.0.0.1:1/disposable_test"
    )
    failed = client.run(OperatorAction.STOP_ALL)
    assert failed.returncode != 0 and OPERATION_FAILED_DETAIL in failed.stderr
    assert "private-secret" not in failed.stderr + failed.stdout


def test_operation_schema_matches_metadata_and_rejects_invalid_audit_states(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            async with sessions() as session:
                connection = await session.connection()

                def inspect_tables(sync_connection):
                    inspector = inspect(sync_connection)
                    return {
                        table: (
                            [column["name"] for column in inspector.get_columns(table)],
                            {
                                constraint["name"]
                                for constraint in inspector.get_check_constraints(table)
                            },
                        )
                        for table in (CONTROL_TABLE, AUDIT_TABLE)
                    }

                reflected = await connection.run_sync(inspect_tables)
                for row_type in (OperationControlRow, OperatorAuditRow):
                    assert set(reflected[row_type.__tablename__][0]) == set(
                        row_type.__table__.columns.keys()
                    )
                assert {AUDIT_ACTION_CONSTRAINT, AUDIT_OUTCOME_CONSTRAINT} <= reflected[
                    AUDIT_TABLE
                ][1]
                session.add(
                    OperatorAuditRow(
                        actor="test", action="invalid", outcome=OperatorOutcome.APPLIED
                    )
                )
                with pytest.raises(StatementError):
                    await session.flush()

    asyncio.run(scenario())


@pytest.mark.parametrize("path", ["", "relative/path"])
def test_storage_probe_requires_absolute_configuration(path):
    with pytest.raises(ValueError, match="absolute path"):
        StartupSettings(
            database_url="fixture", redis_url="fixture", storage_probe_path=path
        )
