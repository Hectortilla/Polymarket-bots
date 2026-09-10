"""Explicit local startup creates one real verified identity using ordinary auth."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from api.auth.contracts import Credentials, LoginCredentials
from api.auth.development import (
    DEVELOPMENT_EMAIL,
    DEVELOPMENT_PASSWORD,
    DevelopmentAccountStore,
)
from api.auth.models import UserRow
from api.auth.passwords import hash_password, verify_password
from api.auth.policy import LOGIN_PATH, ME_PATH, PASSWORD_MAX_LENGTH, REGISTER_PATH
from api.auth.recovery.contracts import ChangePasswordRequest, ReauthenticateRequest
from api.auth.recovery.policy import ACCOUNT_PATH, PASSWORD_CHANGE_PATH
from api.database import DATABASE_URL_ENV
from api.deployment.settings import ENVIRONMENT_ENV, Environment, StartupSettings
from api.execution.config import REDIS_URL_ENV
from api.http.dependencies import application_lifespan
from api.http.routes.paths import api_route_path
from fastapi import status
from polybot.framework.clock import system_now_utc
from sqlmodel import select

from control_plane.test_auth import PASSWORD, run_scenario
from control_plane.test_auth import services as services  # noqa: PLC0414


@pytest.mark.parametrize(
    "environment", [None, Environment.DEVELOPMENT, Environment.PRODUCTION, "dev"]
)
def test_only_explicit_development_enables_seeding(monkeypatch, environment):
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql://localhost/local_test")
    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:6379/1")
    monkeypatch.delenv(DATABASE_URL_ENV + "_FILE", raising=False)
    monkeypatch.delenv(REDIS_URL_ENV + "_FILE", raising=False)
    if environment is None:
        monkeypatch.delenv(ENVIRONMENT_ENV, raising=False)
    else:
        monkeypatch.setenv(ENVIRONMENT_ENV, environment)
    if environment in (Environment.PRODUCTION, "dev"):
        with pytest.raises(ValueError):
            StartupSettings.from_env()
    else:
        assert StartupSettings.from_env().seed_development_account == (
            environment == Environment.DEVELOPMENT
        )


def test_production_settings_reject_seeding():
    with pytest.raises(ValueError, match="forbids development account"):
        StartupSettings(
            database_url="unused",
            redis_url="unused",
            environment=Environment.PRODUCTION,
            seed_development_account=True,
            release_id="a" * 40,
            proxy_address="127.0.0.1",
        )


def test_existing_password_input_does_not_relax_new_password_policy():
    assert (
        LoginCredentials(
            email=DEVELOPMENT_EMAIL, password=DEVELOPMENT_PASSWORD
        ).password.get_secret_value()
        == DEVELOPMENT_PASSWORD
    )
    assert ReauthenticateRequest(current_password=DEVELOPMENT_PASSWORD)
    for password in ("", "x" * (PASSWORD_MAX_LENGTH + 1)):
        with pytest.raises(ValueError):
            LoginCredentials(email=DEVELOPMENT_EMAIL, password=password)
        with pytest.raises(ValueError):
            ReauthenticateRequest(current_password=password)
    with pytest.raises(ValueError):
        Credentials(email=DEVELOPMENT_EMAIL, password=DEVELOPMENT_PASSWORD)
    with pytest.raises(ValueError):
        ChangePasswordRequest(
            current_password=DEVELOPMENT_PASSWORD, new_password=DEVELOPMENT_PASSWORD
        )


def development_settings(enabled=True):
    return StartupSettings(
        database_url="unused", redis_url="unused", seed_development_account=enabled
    )


def test_startup_seed_login_verification_and_password_change(services):
    async def scenario(client, app, factory, redis, launcher):
        app.state.startup_settings = development_settings()
        async with application_lifespan(app):
            response = await client.post(
                api_route_path(LOGIN_PATH),
                json={"email": DEVELOPMENT_EMAIL, "password": DEVELOPMENT_PASSWORD},
            )
            assert response.status_code == status.HTTP_200_OK, response.text
            identity = response.json()
            assert (await client.get(api_route_path(ME_PATH))).json() == identity
            assert (await client.get(api_route_path(ACCOUNT_PATH))).json()[
                "email_verified"
            ] is True
            async with factory() as session:
                user = (await session.execute(select(UserRow))).scalar_one()
                assert user.can_launch_runs and user.verification_required
                assert user.password_hash != DEVELOPMENT_PASSWORD
                assert await verify_password(user.password_hash, DEVELOPMENT_PASSWORD)
            wrong = await client.post(
                api_route_path(LOGIN_PATH),
                json={"email": DEVELOPMENT_EMAIL, "password": "b"},
            )
            assert wrong.status_code == status.HTTP_401_UNAUTHORIZED
            registration = await client.post(
                api_route_path(REGISTER_PATH),
                json={"email": "another@example.com", "password": DEVELOPMENT_PASSWORD},
            )
            assert registration.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
            changed = await client.post(
                api_route_path(PASSWORD_CHANGE_PATH),
                json={
                    "current_password": DEVELOPMENT_PASSWORD,
                    "new_password": PASSWORD,
                },
            )
            assert changed.status_code == status.HTTP_200_OK, changed.text
        async with application_lifespan(app):
            old = await client.post(
                api_route_path(LOGIN_PATH),
                json={"email": DEVELOPMENT_EMAIL, "password": DEVELOPMENT_PASSWORD},
            )
            assert old.status_code == status.HTTP_401_UNAUTHORIZED
            current = await client.post(
                api_route_path(LOGIN_PATH),
                json={"email": DEVELOPMENT_EMAIL, "password": PASSWORD},
            )
            assert current.status_code == status.HTTP_200_OK
            assert current.json() == identity

    asyncio.run(run_scenario(services, scenario))


def test_concurrent_seed_preserves_existing_account_state(services):
    async def scenario(client, app, factory, redis, launcher):
        async def seed():
            async with factory() as session:
                await DevelopmentAccountStore(session).ensure_account()

        await asyncio.gather(seed(), seed(), seed())
        async with factory() as session:
            user = (await session.execute(select(UserRow))).scalar_one()
            identity = user.id
            user.password_hash = await hash_password(PASSWORD)
            user.email_verified_at = None
            user.suspended_at = system_now_utc()
            user.restore_quarantined_at = system_now_utc()
            await session.commit()
            before = user.model_dump()
        await asyncio.gather(seed(), seed())
        async with factory() as session:
            user = (await session.execute(select(UserRow))).scalar_one()
            assert user.id == identity
            assert user.model_dump() == before

    asyncio.run(run_scenario(services, scenario))


def test_disabled_startup_does_not_seed(services):
    async def scenario(client, app, factory, redis, launcher):
        app.state.startup_settings = development_settings(enabled=False)
        async with application_lifespan(app), factory() as session:
            assert (await session.execute(select(UserRow))).scalars().all() == []

    asyncio.run(run_scenario(services, scenario))


def test_seed_failure_aborts_startup(services):
    async def scenario(client, app, factory, redis, launcher):
        app.state.startup_settings = development_settings()
        with (
            patch.object(
                DevelopmentAccountStore,
                "ensure_account",
                AsyncMock(side_effect=RuntimeError("seed unavailable")),
            ),
            pytest.raises(RuntimeError, match="seed unavailable"),
        ):
            async with application_lifespan(app):
                pytest.fail("failed seed must abort startup")

    asyncio.run(run_scenario(services, scenario))
