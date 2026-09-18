"""Real-session authorization, safe inspection and operator privilege changes."""

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from api.admin.policy import (
    ADMIN_LOGIN_REDIRECT,
    ADMIN_PATH,
    CONFIGURATION_VIEW_ID,
    RUN_VIEW_ID,
    USER_VIEW_ID,
)
from api.auth.models import SessionRow, UserRow
from api.auth.policy import ME_PATH, REGISTER_PATH, SESSION_COOKIE
from api.auth.store import AuthStore
from api.bots.models import BotRow
from api.http.routes.paths import BOT_PATH, api_route_path
from api.operations.control import OperatorControl
from api.operations.models import OperatorAuditRow
from api.operations.schema import OperatorAction, OperatorOutcome
from api.runs.models import RunRow
from polybot.framework.clock import system_now_utc
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

from control_plane.limits_fixtures import account_bot, queue_run, resource_services
from control_plane.limits_fixtures import limits_services as limits_services  # noqa: PLC0414 - pytest fixture
from control_plane.test_auth import run_scenario
from control_plane.test_operation_cli import OperatorCommandClient


@pytest.fixture
def admin_services(limits_services):
    yield limits_services

    # Only disposable test rows: permit the test harness to exercise downgrade/base.
    async def cleanup():
        async with resource_services(limits_services) as (sessions, _):
            async with sessions() as session:
                await session.execute(
                    delete(OperatorAuditRow).where(
                        OperatorAuditRow.action.in_(
                            [OperatorAction.GRANT_ADMIN, OperatorAction.REVOKE_ADMIN]
                        )
                    )
                )
                await session.commit()

    asyncio.run(cleanup())


async def identity(sessions, *, admin=False):
    user, bot = await account_bot(sessions)
    async with sessions() as session:
        row = await session.get(UserRow, user.id)
        row.email_verified_at = system_now_utc()
        row.is_admin = admin
        token = await AuthStore(session).issue_session(row, None)
    return user, bot, token


def path(identity, suffix="list"):
    return f"{ADMIN_PATH}/{identity}/{suffix}"


def test_admin_boundary_covers_entire_mount_and_existing_api_isolation(admin_services):
    async def scenario(client, app, sessions, redis, launcher):
        user, bot, normal_token = await identity(sessions)
        _admin, _, admin_token = await identity(sessions, admin=True)
        run = await queue_run(sessions, bot)
        protected = [
            ADMIN_PATH,
            ADMIN_PATH + "/",
            path(USER_VIEW_ID),
            path(CONFIGURATION_VIEW_ID),
            path(RUN_VIEW_ID),
            path(USER_VIEW_ID, f"details/{user.id}"),
            path(USER_VIEW_ID, "ajax/lookup"),
            path(USER_VIEW_ID, "export/csv"),
            ADMIN_PATH + "/statics/css/main.css",
        ]
        for url in protected:
            response = await client.get(url)
            assert response.status_code == 302, (url, response.text)
            assert response.headers["location"] == ADMIN_LOGIN_REDIRECT
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-frame-options"] == "DENY"
        client.cookies.set(SESSION_COOKIE, normal_token.value)
        for url in protected:
            assert (await client.get(url)).status_code == 403
        client.cookies.set(SESSION_COOKIE, admin_token.value)
        for url in [
            ADMIN_PATH + "/",
            path(USER_VIEW_ID),
            path(CONFIGURATION_VIEW_ID),
            path(RUN_VIEW_ID),
            path(USER_VIEW_ID, f"details/{user.id}"),
            path(RUN_VIEW_ID, f"details/{run.id}"),
        ]:
            response = await client.get(url)
            assert response.status_code == 200, (url, response.text)
            assert "password_hash" not in response.text
            assert "execution_token" not in response.text
        assert (
            await client.get(api_route_path(BOT_PATH).format(bot_id=bot.id))
        ).status_code == 404
        assert (await client.get(api_route_path(ME_PATH))).json()["is_admin"] is True
        assert app.state.session_factory.kw["autoflush"] is True
        for suffix in [
            "create",
            "edit/" + str(user.id),
            "export/csv",
            "ajax/lookup",
            "import",
            "action/mutate",
        ]:
            assert (await client.get(path(USER_VIEW_ID, suffix))).status_code in {
                404,
                405,
            }
        for method in ["post", "put", "patch", "delete"]:
            assert (
                await client.request(method, path(USER_VIEW_ID, "delete"), json={})
            ).status_code == 405
        assert (
            await client.get(path(USER_VIEW_ID, "details/not-a-uuid"))
        ).status_code == 404
        assert (
            await client.get(path(USER_VIEW_ID, f"details/{uuid4()}"))
        ).status_code == 404
        assert (
            await client.post(
                api_route_path(REGISTER_PATH),
                json={
                    "email": "escalate@example.com",
                    "password": "safe test password 123",
                    "is_admin": True,
                },
            )
        ).status_code == 422

    asyncio.run(run_scenario(admin_services, scenario))


def test_inspection_filters_snapshots_pagination_and_escaped_content(admin_services):
    async def scenario(client, app, sessions, redis, launcher):
        _admin, _, token = await identity(sessions, admin=True)
        user, bot, _ = await identity(sessions)
        other, other_bot, _ = await identity(sessions)
        run = await queue_run(sessions, bot)
        other_run = await queue_run(sessions, other_bot)
        async with sessions() as session:
            await session.execute(
                update(BotRow)
                .where(BotRow.id == bot.id)
                .values(
                    deleted_at=system_now_utc(),
                    config={
                        "name": "<script>alert(1)</script>",
                        "graph": {"nodes": []},
                    },
                )
            )
            await session.execute(
                update(RunRow)
                .where(RunRow.id == run.id)
                .values(failure_detail="<script>alert(2)</script>")
            )
            await session.commit()
        client.cookies.set(SESSION_COOKIE, token.value)
        response = await client.get(path(CONFIGURATION_VIEW_ID, f"details/{bot.id}"))
        assert response.status_code == 200
        assert "Deleted configuration" in response.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
        response = await client.get(path(RUN_VIEW_ID, f"details/{run.id}"))
        assert response.status_code == 200
        assert "capacity test" in response.text and "alert(1)" not in response.text
        assert "&lt;script&gt;alert(2)&lt;/script&gt;" in response.text
        for params in [
            {"owner_user_id": str(user.id)},
            {"bot_id": str(bot.id)},
            {"search": user.email},
        ]:
            response = await client.get(path(RUN_VIEW_ID), params=params)
            assert response.status_code == 200, response.text
            assert (
                str(run.id) in response.text and str(other_run.id) not in response.text
            )
        response = await client.get(path(USER_VIEW_ID), params={"search": user.email})
        assert user.email in response.text and other.email not in response.text
        assert (
            await client.get(path(RUN_VIEW_ID), params={"status": "failed"})
        ).status_code == 200
        for params in [
            {"owner_user_id": "invalid"},
            {"bot_id": "invalid"},
            {"status": "invalid"},
            {"sortBy": "password_hash"},
        ]:
            assert (
                await client.get(path(RUN_VIEW_ID), params=params)
            ).status_code == 400
        # Exercise the library's hard maximum using more records than one page.
        async with sessions() as session:
            session.add_all(
                UserRow(email=f"page-{i}@example.com", password_hash="must-not-render")
                for i in range(105)
            )
            await session.commit()
        response = await client.get(path(USER_VIEW_ID), params={"pageSize": "10000"})
        assert response.status_code == 200
        assert response.text.count('title="View"') == 100
        assert "must-not-render" not in response.text

    asyncio.run(run_scenario(admin_services, scenario))


@pytest.mark.parametrize(
    "change", ["demote", "suspend", "quarantine", "expire", "revoke"]
)
def test_admin_authorization_rechecks_database_every_request(admin_services, change):
    async def scenario(client, app, sessions, redis, launcher):
        user, _, token = await identity(sessions, admin=True)
        client.cookies.set(SESSION_COOKIE, token.value)
        assert (await client.get(path(USER_VIEW_ID))).status_code == 200
        async with sessions() as session:
            if change == "demote":
                await session.execute(
                    update(UserRow).where(UserRow.id == user.id).values(is_admin=False)
                )
            elif change in {"suspend", "quarantine"}:
                field = (
                    UserRow.suspended_at
                    if change == "suspend"
                    else UserRow.restore_quarantined_at
                )
                await session.execute(
                    update(UserRow)
                    .where(UserRow.id == user.id)
                    .values({field: system_now_utc()})
                )
            elif change == "expire":
                await session.execute(
                    update(SessionRow)
                    .where(SessionRow.user_id == user.id)
                    .values(expires_at=system_now_utc() - timedelta(seconds=1))
                )
            else:
                await AuthStore(session).revoke(token)
            await session.commit()
        assert (await client.get(path(USER_VIEW_ID))).status_code == (
            403 if change == "demote" else 302
        )

    asyncio.run(run_scenario(admin_services, scenario))


def test_operator_grants_revokes_audits_and_invalidates_sessions(admin_services):
    async def seed():
        async with resource_services(admin_services) as (sessions, _):
            user, _, token = await identity(sessions)
            invalid, _ = await account_bot(sessions)
            return user.id, token, invalid.id

    user_id, token, invalid_id = asyncio.run(seed())
    cli = OperatorCommandClient(admin_services)
    assert cli.run(OperatorAction.GRANT_ADMIN, invalid_id).returncode != 0
    assert cli.run(OperatorAction.GRANT_ADMIN, user_id).returncode == 0
    assert cli.run(OperatorAction.GRANT_ADMIN, user_id).returncode == 0

    async def check():
        async with resource_services(admin_services) as (sessions, _):
            async with sessions() as session:
                assert (await session.get(UserRow, user_id)).is_admin is True
                assert await AuthStore(session).current_user(token) is None
                rows = list(
                    await session.scalars(
                        select(OperatorAuditRow).order_by(OperatorAuditRow.occurred_at)
                    )
                )
                assert [row.outcome for row in rows] == [
                    OperatorOutcome.APPLIED,
                    OperatorOutcome.UNCHANGED,
                ]
                assert all(row.actor and row.target == user_id for row in rows)
                user = await session.get(UserRow, user_id)
                return await AuthStore(session).issue_session(user, None)

    admin_token = asyncio.run(check())
    assert cli.run(OperatorAction.REVOKE_ADMIN, user_id).returncode == 0

    async def check_revoked():
        async with (
            resource_services(admin_services) as (sessions, _),
            sessions() as session,
        ):
            assert (await session.get(UserRow, user_id)).is_admin is False
            assert await AuthStore(session).current_user(admin_token) is None
            assert (
                await session.scalars(
                    select(OperatorAuditRow).where(
                        OperatorAuditRow.action == OperatorAction.REVOKE_ADMIN
                    )
                )
            ).one().outcome is OperatorOutcome.APPLIED

    asyncio.run(check_revoked())


def test_database_failure_denies_admin_without_private_error_details(admin_services):
    async def scenario(client, app, sessions, redis, launcher):
        _, _, token = await identity(sessions, admin=True)
        client.cookies.set(SESSION_COOKIE, token.value)
        with patch.object(
            AuthStore,
            "current_user",
            side_effect=OperationalError(
                "sensitive statement", {}, Exception("private secret")
            ),
        ):
            response = await client.get(path(USER_VIEW_ID))
        assert response.status_code == 503
        assert (
            "private secret" not in response.text
            and "sensitive statement" not in response.text
        )
        assert response.headers["cache-control"] == "no-store"

    asyncio.run(run_scenario(admin_services, scenario))


def test_upgrade_preserves_existing_accounts_without_promotion(admin_services):
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_services[0])
    command.downgrade(config, "0001")
    user_id = uuid4()

    async def seed():
        async with resource_services(admin_services) as (sessions, _):
            async with sessions() as session:
                await session.execute(
                    text(
                        "INSERT INTO users (id,email,password_hash,created_at) VALUES (:id,:email,:hash,:now)"
                    ),
                    {
                        "id": user_id,
                        "email": "pre-migration@example.com",
                        "hash": "preserved",
                        "now": system_now_utc(),
                    },
                )
                await session.commit()

    asyncio.run(seed())
    command.upgrade(config, "head")

    async def check():
        async with resource_services(admin_services) as (sessions, _):
            async with sessions() as session:
                user = await session.get(UserRow, user_id)
                assert user.is_admin is False and user.password_hash == "preserved"

    asyncio.run(check())


@pytest.mark.parametrize("field", ["suspended_at", "restore_quarantined_at"])
def test_admin_grants_reject_inactive_verified_accounts(admin_services, field):
    async def scenario(client, app, sessions, redis, launcher):
        user, _, _ = await identity(sessions)
        async with sessions() as session:
            await session.execute(
                update(UserRow)
                .where(UserRow.id == user.id)
                .values({field: system_now_utc()})
            )
            await session.commit()
            with pytest.raises(ValueError, match="verified, active"):
                await OperatorControl(session, "test").apply(
                    OperatorAction.GRANT_ADMIN, user.id
                )
            await session.rollback()
            assert (await session.get(UserRow, user.id)).is_admin is False

    asyncio.run(run_scenario(admin_services, scenario))


def test_downgrade_cannot_erase_admin_audit_history(admin_services):
    async def seed():
        async with resource_services(admin_services) as (sessions, _):
            user, _, _ = await identity(sessions)
            async with sessions() as session:
                await OperatorControl(session, "migration-test").apply(
                    OperatorAction.GRANT_ADMIN, user.id
                )
            return user.id

    user_id = asyncio.run(seed())
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_services[0])
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0001")

    async def check():
        async with (
            resource_services(admin_services) as (sessions, _),
            sessions() as session,
        ):
            assert (await session.get(UserRow, user_id)).is_admin is True
            assert (
                await session.scalars(select(OperatorAuditRow))
            ).one().target == user_id
            assert (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                == "0002"
            )

    asyncio.run(check())
