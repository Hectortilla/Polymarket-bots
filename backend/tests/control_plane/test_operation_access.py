"""Account suspension serializes with HTTP credentials and private paper execution."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from api.auth.access import AccountAccessStore
from api.auth.config import AuthSettings
from api.auth.models import SessionRow, UserRow
from api.auth.passwords import hash_password
from api.auth.policy import AUTH_RATE_LIMIT_KEY_PREFIX, LOGIN_PATH, ME_PATH
from api.auth.recovery.errors import InvalidAccountToken
from api.auth.recovery.models import AccountTokenRow
from api.auth.recovery.policy import (
    RESET_COMPLETE_PATH,
    TOKEN_INVALID_DETAIL,
    VERIFY_COMPLETE_PATH,
    TokenPurpose,
)
from api.auth.recovery.store import AccountCredentialStore
from api.auth.routes import verify_password
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.execution.worker.lifecycle import RunLifecycleCoordinator
from api.http.app import create_app
from api.http.routes.paths import api_route_path
from api.limits.admission import RunAdmission
from api.operations.control import OperatorControl
from api.operations.control.accounts import AccountControls
from api.operations.models import OperationControlRow
from api.operations.schema import OperatorAction
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.status import RunStatus
from api.runs.store import RunStore
from fastapi import status
from httpx import ASGITransport, AsyncClient
from polybot.framework.clock import system_now_utc
from sqlalchemy import select, update

from control_plane.auth_fixtures import TEST_HEADERS, TEST_ORIGIN
from control_plane.limits_fixtures import (
    account_bot,
    claim_run,
    queue_run,
    resource_services,
)
from control_plane.limits_fixtures import limits_services as limits_services

PASSWORD = "a long disposable account password"
ACTOR = "access-test-operator"


def test_login_and_suspension_serialize_in_both_orders(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            async for key in redis.scan_iter(AUTH_RATE_LIMIT_KEY_PREFIX + "*"):
                await redis.delete(key)
            user, _ = await account_bot(sessions)
            async with sessions() as session:
                await session.execute(
                    update(UserRow)
                    .where(UserRow.id == user.id)
                    .values(password_hash=await hash_password(PASSWORD))
                )
                await session.commit()
            app = create_app(
                auth_settings=AuthSettings(TEST_ORIGIN, allow_http=True),
                session_factory=sessions,
                redis=redis,
                launcher=AsyncMock(),
            )
            locked, release = asyncio.Event(), asyncio.Event()

            async def gated_verify(*args):
                locked.set()
                await release.wait()
                return await verify_password(*args)

            async def suspend():
                async with sessions() as session:
                    await OperatorControl(session, ACTOR).apply(
                        OperatorAction.SUSPEND, user.id
                    )

            async with AsyncClient(
                transport=ASGITransport(app), base_url=TEST_ORIGIN, headers=TEST_HEADERS
            ) as client:
                with patch("api.auth.routes.verify_password", gated_verify):
                    login = asyncio.create_task(
                        client.post(
                            api_route_path(LOGIN_PATH),
                            json={"email": user.email, "password": PASSWORD},
                        )
                    )
                    await locked.wait()
                    suspension = asyncio.create_task(suspend())
                    release.set()
                    response, _ = await asyncio.gather(login, suspension)
                assert response.status_code == status.HTTP_200_OK
                assert (
                    await client.get(api_route_path(ME_PATH))
                ).status_code == status.HTTP_401_UNAUTHORIZED
                async with sessions() as session:
                    await OperatorControl(session, ACTOR).apply(
                        OperatorAction.RESUME_ACCOUNT, user.id
                    )
                locked.clear()
                release.clear()
                original_suspend = AccountControls.suspend

                async def gated_suspend(self, owner):
                    outcome = await original_suspend(self, owner)
                    locked.set()
                    await release.wait()
                    return outcome

                with patch.object(AccountControls, "suspend", gated_suspend):
                    suspension = asyncio.create_task(suspend())
                    await locked.wait()
                    login = asyncio.create_task(
                        client.post(
                            api_route_path(LOGIN_PATH),
                            json={"email": user.email, "password": PASSWORD},
                        )
                    )
                    release.set()
                    _, response = await asyncio.gather(suspension, login)
                assert response.status_code == status.HTTP_401_UNAUTHORIZED
                async with sessions() as session:
                    assert (
                        list(
                            await session.scalars(
                                select(SessionRow).where(SessionRow.user_id == user.id)
                            )
                        )
                        == []
                    )
                # No ordinary account has a reachable operations API.
                assert not any("operations" in path for path in app.openapi()["paths"])

    asyncio.run(scenario())


@pytest.mark.parametrize("purpose", list(TokenPurpose))
def test_suspension_invalidates_recovery_and_cannot_issue_new_tokens(
    limits_services, purpose
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, _ = await account_bot(sessions)
            async with sessions() as session:
                token = await AccountCredentialStore(session).issue_link(
                    user.email, purpose
                )
                await OperatorControl(session, ACTOR).apply(
                    OperatorAction.SUSPEND, user.id
                )
                await AccountCredentialStore(session).issue_link(user.email, purpose)
                assert (
                    list(
                        await session.scalars(
                            select(AccountTokenRow).where(
                                AccountTokenRow.user_id == user.id
                            )
                        )
                    )
                    == []
                )
            app = create_app(
                auth_settings=AuthSettings(TEST_ORIGIN, allow_http=True),
                session_factory=sessions,
                redis=redis,
                launcher=AsyncMock(),
            )
            path = (
                VERIFY_COMPLETE_PATH if purpose.verifies_email else RESET_COMPLETE_PATH
            )
            async with AsyncClient(
                transport=ASGITransport(app), base_url=TEST_ORIGIN, headers=TEST_HEADERS
            ) as client:
                response = await client.post(
                    api_route_path(path),
                    json={"token": token.value, "new_password": PASSWORD},
                )
                assert response.status_code == status.HTTP_400_BAD_REQUEST
                assert response.json()["detail"] == TOKEN_INVALID_DETAIL
            async with sessions() as session:
                persisted = await session.get(UserRow, user.id)
                assert persisted.password_hash == user.password_hash
                assert persisted.email_verified_at is None

    asyncio.run(scenario())


def test_suspend_scopes_queued_and_active_termination_to_one_account(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            first, first_bot = await account_bot(sessions)
            second, second_bot = await account_bot(sessions)
            first_active = await queue_run(sessions, first_bot)
            await claim_run(sessions, first_active)
            first_queued = await queue_run(sessions, first_bot)
            second_active = await queue_run(sessions, second_bot)
            await claim_run(sessions, second_active)
            second_queued = await queue_run(sessions, second_bot)
            async with sessions() as session:
                await OperatorControl(session, ACTOR).apply(
                    OperatorAction.SUSPEND, first.id
                )
                store = RunStore(session)
                assert (
                    await store.read(first_active.id)
                ).status is RunStatus.INTERRUPTED
                assert (await store.read(first_queued.id)).status is RunStatus.STOPPED
                assert (await store.read(second_active.id)).status is RunStatus.STARTING
                assert (await store.read(second_queued.id)).status is RunStatus.QUEUED
                for run in (first_active, first_queued):
                    assert len(await EventStore(session).read(run.id)) == 1
                for run in (second_active, second_queued):
                    assert await EventStore(session).read(run.id) == ()

    asyncio.run(scenario())


def test_claim_guards_reject_paused_and_suspended_persisted_queue(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            first, first_bot = await account_bot(sessions)
            _, second_bot = await account_bot(sessions)
            first_run = await queue_run(sessions, first_bot)
            second_run = await queue_run(sessions, second_bot)
            async with sessions() as session:
                await session.execute(
                    update(OperationControlRow).values(admissions_paused=True)
                )
                await session.commit()
                assert (
                    await RunStore(session).claim(first_run.id, now=system_now_utc())
                    is None
                )
                await session.execute(
                    update(UserRow)
                    .where(UserRow.id == first.id)
                    .values(suspended_at=system_now_utc())
                )
                await session.execute(
                    update(OperationControlRow).values(admissions_paused=False)
                )
                await session.commit()
                assert (
                    await RunAdmission(session).next_eligible_queued_run_id()
                    == second_run.id
                )
                await session.commit()
            assert await claim_run(sessions, first_run) is None
            assert await claim_run(sessions, second_run) is not None

    asyncio.run(scenario())


def test_operator_stop_cancels_owned_runtime_on_next_worker_poll(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            _, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            started, cleaned = asyncio.Event(), asyncio.Event()

            async def runtime(*args, **kwargs):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()

            async with sessions() as session:
                coordinator = RunLifecycleCoordinator(
                    RunStore(session),
                    sessions,
                    RunEventWriter(sessions, redis),
                    heartbeat_seconds=0.01,
                    lease_seconds=DEFAULT_LEASE_SECONDS,
                )
                with patch("api.execution.worker.lifecycle.run_claimed_bot", runtime):
                    task = asyncio.create_task(coordinator.execute(run.id))
                    await asyncio.wait_for(started.wait(), 2)
                    async with sessions() as operator_session:
                        await OperatorControl(operator_session, ACTOR).apply(
                            OperatorAction.STOP_RUN, run.id
                        )
                    await asyncio.wait_for(task, 2)
                    assert cleaned.is_set()
            async with sessions() as session:
                assert (
                    await RunStore(session).read(run.id)
                ).status is RunStatus.INTERRUPTED
                assert len(await EventStore(session).read(run.id)) == 1

    asyncio.run(scenario())


def test_suspension_wins_after_recovery_reads_a_token_owner(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            user, _ = await account_bot(sessions)
            async with sessions() as session:
                token = await AccountCredentialStore(session).issue_link(
                    user.email, TokenPurpose.RESET
                )
            owner_read, release = asyncio.Event(), asyncio.Event()
            original_lock = AccountAccessStore.require_locked_account

            async def delayed_lock(self, owner):
                owner_read.set()
                await release.wait()
                return await original_lock(self, owner)

            async def redeem():
                async with sessions() as session:
                    await AccountCredentialStore(session).redeem(
                        token, TokenPurpose.RESET, "replacement hash"
                    )

            with patch.object(
                AccountAccessStore, "require_locked_account", delayed_lock
            ):
                redemption = asyncio.create_task(redeem())
                await owner_read.wait()
                async with sessions() as session:
                    await OperatorControl(session, ACTOR).apply(
                        OperatorAction.SUSPEND, user.id
                    )
                release.set()
                with pytest.raises(InvalidAccountToken):
                    await redemption
            async with sessions() as session:
                assert (
                    await session.get(UserRow, user.id)
                ).password_hash == user.password_hash

    asyncio.run(scenario())
