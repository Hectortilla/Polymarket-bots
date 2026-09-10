"""Disposable services and owned rows shared by resource tests and load rehearsal."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from api.auth.config import AuthSettings
from api.auth.contracts import CurrentUser
from api.auth.dependencies import application_authentication
from api.auth.models import UserRow
from api.bots.store import BotStore
from api.catalog.definitions import CATALOG, WINNER_DEFINITION_ID
from api.deployment.settings import StartupSettings
from api.execution.worker.resources import drain_queued_runs_with_worker_resources
from api.http.app import create_app
from api.limits.errors import ResourceLimitError
from api.limits.redis.contracts import RESOURCE_KEY_PREFIX
from api.operations.telemetry.keys import OPERATIONS_TELEMETRY_KEY_NAMESPACE
from api.runs.store import RunStore
from fastapi import Request
from polybot.framework.clock import system_now_utc
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from control_plane.auth_fixtures import TEST_ORIGIN
from control_plane.disposable_services import (
    disposable_postgres_url,
    disposable_redis_url,
)
from control_plane.service_config import (
    POSTGRES_AND_REDIS_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
    TEST_REDIS_URL_ENV,
)


@pytest.fixture
def limits_services():
    postgres = os.getenv(TEST_POSTGRES_URL_ENV)
    redis = os.getenv(TEST_REDIS_URL_ENV)
    if not postgres or not redis:
        pytest.skip(POSTGRES_AND_REDIS_NOT_CONFIGURED_SKIP_REASON)
    url = disposable_postgres_url(postgres).render_as_string(hide_password=False)
    redis = disposable_redis_url(redis)
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return url, redis


@asynccontextmanager
async def resource_services(settings):
    url, redis_url = settings
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(redis_url)
    for prefix in (RESOURCE_KEY_PREFIX, OPERATIONS_TELEMETRY_KEY_NAMESPACE):
        async for key in redis.scan_iter(prefix + "*"):
            await redis.delete(key)
    try:
        yield sessions, redis
    finally:
        await redis.aclose()
        await engine.dispose()


async def account_bot(sessions):
    async with sessions() as session:
        user = UserRow(
            email=f"{uuid4()}@example.com",
            password_hash="fixture",
            verification_required=False,
        )
        session.add(user)
        await session.commit()
        bot = await BotStore(session, user.id).create(
            definition_id=WINNER_DEFINITION_ID,
            config=CATALOG[WINNER_DEFINITION_ID]
            .parse_config({"name": "capacity test"})
            .model_copy(update={"graph": None}, deep=True),
        )
        return user, bot


async def queue_run(sessions, bot):
    async with sessions() as session:
        return await RunStore(session).create_from_bot(bot)


async def claim_run(sessions, run):
    async with sessions() as session:
        return await RunStore(session).claim(run.id, now=system_now_utc())


def process_queue_attempt(url, bot):
    """A separate process owns a separate engine, like another API instance."""

    async def attempt():
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await queue_run(sessions, bot)
            return True
        except ResourceLimitError:
            return False
        finally:
            await engine.dispose()

    return asyncio.run(attempt())


def account_app(sessions, redis, account):
    app = create_app(
        auth_settings=AuthSettings(TEST_ORIGIN, allow_http=True),
        session_factory=sessions,
        redis=redis,
        launcher=AsyncMock(),
    )

    async def identity(request: Request):
        request.state.user = CurrentUser.from_model(account)
        request.state.session_token = "fixture-token"

    app.dependency_overrides[application_authentication] = identity
    return app


def process_drain_queue(settings):
    """Run the actual worker queue drain with deterministic local bot work."""
    completed = []
    startup = StartupSettings(database_url=settings[0], redis_url=settings[1])

    async def runtime(run, observer, **kwargs):
        completed.append(run.id)
        await asyncio.sleep(0.03)

    with (
        patch.object(StartupSettings, "from_env", return_value=startup),
        patch("api.execution.worker.lifecycle.run_claimed_bot", runtime),
    ):
        asyncio.run(drain_queued_runs_with_worker_resources())
    return completed


def process_gated_queue_drain(settings, started, release):
    startup = StartupSettings(database_url=settings[0], redis_url=settings[1])

    async def runtime(run, observer, **kwargs):
        await asyncio.to_thread(started.append, run.id)
        if not await asyncio.to_thread(release.wait, 15):
            raise TimeoutError("worker capacity test gate was not released")

    with (
        patch.object(StartupSettings, "from_env", return_value=startup),
        patch("api.execution.worker.lifecycle.run_claimed_bot", runtime),
    ):
        asyncio.run(drain_queued_runs_with_worker_resources())
