"""Slice 15 acceptance against real PostgreSQL and shared Redis."""

import asyncio
import json
import os
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from api.auth.config import AuthSettings
from api.auth.contracts import Credentials
from api.auth.models import SessionRow, UserRow
from api.auth.passwords import DUMMY_HASH, HASHER
from api.auth.policy import (
    AUTH_BODY_MAX_BYTES,
    AUTH_REQUIRED_DETAIL,
    LOGIN_ATTEMPT_LIMIT,
    LOGIN_FAILED_DETAIL,
    LOGIN_PATH,
    LOGOUT_PATH,
    ME_PATH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PUBLIC_ROUTES,
    REGISTER_ATTEMPT_LIMIT,
    REGISTER_PATH,
    SESSION_COOKIE,
    SESSION_COOKIE_SAMESITE,
    SESSION_RECHECK_SECONDS,
)
from api.auth.schema import OWNER_USER_ID_COLUMN, SESSIONS_TABLE, USERS_TABLE
from api.auth.store import AuthStore
from api.auth.store.tokens import SESSION_TOKEN_LENGTH, SessionToken
from api.auth.streams import StreamAuthorization
from api.bots.models import BotRow
from api.bots.schema import BOTS_TABLE_NAME
from api.catalog.definitions import NODE_BASED_DEFINITION_ID
from api.catalog.graphs.starter import STARTER_NODE_GRAPH
from api.events.contracts import RunLifecycleEvent, RunStatusPayload
from api.events.ids import FIRST_EVENT_CURSOR
from api.graph_templates.models import GraphTemplateRow
from api.graph_templates.schema import GRAPH_TEMPLATES_TABLE_NAME
from api.http.app import create_app
from api.http.protocol import (
    CACHE_CONTROL_HEADER,
    CONTENT_TYPE_HEADER,
    NO_STORE_CACHE_DIRECTIVE,
    RETRY_AFTER_HEADER,
)
from api.http.routes.paths import (
    BOT_GRAPH_REVISION_PATH,
    BOT_GRAPH_REVISIONS_PATH,
    BOT_PATH,
    BOT_RUNS_PATH,
    BOTS_PATH,
    GRAPH_TEMPLATE_PATH,
    GRAPH_TEMPLATES_PATH,
    HEALTH_PATH,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    RUNS_PATH,
    api_route_path,
)
from api.http.sse import RunEventStreamer
from api.http.sse.replay import RunEventReplay
from api.runs.models import RunRow
from api.runs.status import RunStatus
from api.runs.store import RunStore
from fastapi import status
from httpx import ASGITransport, AsyncClient
from polybot.framework.clock import system_now_utc
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import UniqueConstraint, func, inspect, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select

from control_plane.auth_fixtures import TEST_HEADERS as HEADERS
from control_plane.auth_fixtures import TEST_ORIGIN as ORIGIN
from control_plane.disposable_services import (
    clear_auth_attempts,
    disposable_postgres_url,
    disposable_redis_url,
)
from control_plane.market_fixtures import market_discovery
from control_plane.service_config import (
    POSTGRES_AND_REDIS_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
    TEST_REDIS_URL_ENV,
)

PASSWORD = "correct password for testing"


@pytest.fixture
def services():
    raw = os.getenv(TEST_POSTGRES_URL_ENV)
    redis_url = os.getenv(TEST_REDIS_URL_ENV)
    if not raw or not redis_url:
        pytest.skip(POSTGRES_AND_REDIS_NOT_CONFIGURED_SKIP_REASON)
    url = disposable_postgres_url(raw).render_as_string(hide_password=False)
    redis_url = disposable_redis_url(redis_url)
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    asyncio.run(clear_private_templates(url))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield url, redis_url
    asyncio.run(clear_private_templates(url))
    command.downgrade(config, "base")


async def clear_private_templates(url):
    # Per-owner duplicate names cannot be represented by the old global constraint.
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            if await connection.scalar(text("SELECT to_regclass('graph_templates')")):
                await connection.execute(text("DELETE FROM graph_templates"))
    finally:
        await engine.dispose()


async def run_scenario(services, scenario):
    url, redis_url = services
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(redis_url)
    # This URL points to a dedicated disposable acceptance service.
    await clear_auth_attempts(redis)
    launcher = AsyncMock()
    app = create_app(
        session_factory=factory,
        redis=redis,
        launcher=launcher,
        market_discovery=market_discovery(),
        auth_settings=AuthSettings(ORIGIN, True),
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers=HEADERS
        ) as client:
            await scenario(client, app, factory, redis, launcher)
    finally:
        await redis.aclose()
        await engine.dispose()


async def signup(client, email="first@example.com"):
    result = await client.post(
        api_route_path(REGISTER_PATH), json={"email": email, "password": PASSWORD}
    )
    assert result.status_code == status.HTTP_201_CREATED, result.text
    assert set(result.json()) == {"id", "email"}
    return result


def test_credentials_normalize_without_mail_and_preserve_password():
    assert not HASHER.check_needs_rehash(DUMMY_HASH)
    parsed = Credentials(
        email=" First.Last+tag@EXAMPLE.com ", password=" " + PASSWORD + " "
    )
    assert parsed.email == "first.last+tag@example.com"
    assert parsed.password.get_secret_value() == " " + PASSWORD + " "
    assert PASSWORD not in repr(parsed)
    for password in ["a" * (PASSWORD_MIN_LENGTH - 1), "a" * (PASSWORD_MAX_LENGTH + 1)]:
        with pytest.raises(ValueError):
            Credentials(email="first@example.com", password=password)


def test_auth_and_session_lifecycle(services):
    async def scenario(client, app, factory, redis, launcher):
        assert (
            await client.get(api_route_path(ME_PATH))
        ).status_code == status.HTTP_401_UNAUTHORIZED
        created = await signup(client, "First.Last+tag@EXAMPLE.com")
        assert created.json()["email"] == "first.last+tag@example.com"
        cookie = created.headers["set-cookie"]
        assert (
            "HttpOnly" in cookie
            and f"SameSite={SESSION_COOKIE_SAMESITE}" in cookie
            and "Domain=" not in cookie
        )
        assert created.headers[CACHE_CONTROL_HEADER] == NO_STORE_CACHE_DIRECTIVE
        token = client.cookies.get(SESSION_COOKIE)
        async with factory() as session:
            user = (await session.execute(select(UserRow))).scalar_one()
            stored = (await session.execute(select(SessionRow))).scalar_one()
            assert HASHER.verify(user.password_hash, PASSWORD)
            assert (
                stored.token_digest == SessionToken.parse(token).digest
                and stored.token_digest != token
            )
        # A second API instance shares database sessions, without local cache state.
        other = create_app(
            session_factory=factory,
            redis=redis,
            auth_settings=AuthSettings(ORIGIN, True),
        )
        async with AsyncClient(
            transport=ASGITransport(app=other),
            base_url=ORIGIN,
            cookies={SESSION_COOKIE: token},
        ) as second:
            assert (await second.get(api_route_path(ME_PATH))).json() == created.json()
        duplicate = await client.post(
            api_route_path(REGISTER_PATH),
            json={"email": " FIRST.LAST+TAG@example.com ", "password": PASSWORD},
        )
        assert duplicate.status_code == status.HTTP_409_CONFLICT
        assert "password_hash" not in duplicate.text and PASSWORD not in duplicate.text
        assert (
            await client.post(api_route_path(LOGOUT_PATH))
        ).status_code == status.HTTP_200_OK
        assert (
            await client.post(api_route_path(LOGOUT_PATH))
        ).status_code == status.HTTP_200_OK
        assert (
            await client.get(api_route_path(ME_PATH))
        ).status_code == status.HTTP_401_UNAUTHORIZED
        failures = []
        for email in ["unknown@example.com", created.json()["email"]]:
            response = await client.post(
                api_route_path(LOGIN_PATH),
                json={"email": email, "password": "wrong password long enough"},
            )
            failures.append((response.status_code, response.json()))
        assert (
            failures
            == [(status.HTTP_401_UNAUTHORIZED, {"detail": LOGIN_FAILED_DETAIL})] * 2
        )
        logged_in = await client.post(
            api_route_path(LOGIN_PATH),
            json={"email": created.json()["email"].upper(), "password": PASSWORD},
        )
        assert logged_in.status_code == status.HTTP_200_OK
        assert client.cookies.get(SESSION_COOKIE) != token
        async with factory() as session:
            await session.execute(
                update(SessionRow).values(
                    expires_at=system_now_utc() - timedelta(seconds=1)
                )
            )
            await session.commit()
        assert (
            await client.get(api_route_path(ME_PATH))
        ).status_code == status.HTTP_401_UNAUTHORIZED
        for bad_token in ["garbage", "a" * SESSION_TOKEN_LENGTH, token]:
            client.cookies.clear()
            client.cookies.set(SESSION_COOKIE, bad_token)
            assert (
                await client.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_401_UNAUTHORIZED

    asyncio.run(run_scenario(services, scenario))


def test_auth_ingress_csrf_throttling_and_safe_errors(services):
    async def scenario(client, app, factory, redis, launcher):
        body = {"email": "invalid", "password": PASSWORD, "owner_user_id": str(uuid4())}
        for origin in ["", "http://foreign.example"]:
            result = await client.post(
                api_route_path(REGISTER_PATH), json=body, headers={"Origin": origin}
            )
            assert result.status_code == status.HTTP_403_FORBIDDEN
        result = await client.post(
            api_route_path(LOGIN_PATH),
            json=body,
            headers={CONTENT_TYPE_HEADER: "text/plain"},
        )
        assert result.status_code == status.HTTP_403_FORBIDDEN
        result = await client.post(api_route_path(REGISTER_PATH), json=body)
        assert (
            result.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
            and PASSWORD not in result.text
        )
        assert "input" not in result.json()["detail"][0]
        result = await client.post(
            api_route_path(LOGIN_PATH),
            content=json.dumps({"password": "x" * AUTH_BODY_MAX_BYTES}),
        )
        assert result.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        # Invalid attempts count too; changing forwarded headers cannot evade the quota.
        for _ in range(REGISTER_ATTEMPT_LIMIT - 1):
            assert (
                await client.post(api_route_path(REGISTER_PATH), json=body)
            ).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        limited = await client.post(
            api_route_path(REGISTER_PATH),
            json=body,
            headers={"X-Forwarded-For": "different"},
        )
        assert (
            limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            and int(limited.headers[RETRY_AFTER_HEADER]) > 0
        )
        with patch.object(
            redis,
            "eval",
            AsyncMock(side_effect=RedisConnectionError("secret infrastructure detail")),
        ):
            unavailable = await client.post(api_route_path(LOGIN_PATH), json=body)
            assert (
                unavailable.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
                and "secret" not in unavailable.text
            )
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(UserRow)) == 0

    asyncio.run(run_scenario(services, scenario))


def test_public_allowlist_is_complete_and_other_routes_are_gated(services):
    async def scenario(client, app, factory, redis, launcher):
        actual_public = set()
        for route_path, operations in app.openapi()["paths"].items():
            for method in operations:
                method = method.upper()
                if (method, route_path) in PUBLIC_ROUTES:
                    actual_public.add((method, route_path))
                    continue
                path = re.sub(r"\{[^}]+\}", lambda _: str(uuid4()), route_path)
                response = await client.request(
                    method, path, json={} if method in {"POST", "PATCH"} else None
                )
                assert response.status_code == status.HTTP_401_UNAUTHORIZED, (
                    method,
                    path,
                    response.text,
                )
                assert response.json() == {"detail": AUTH_REQUIRED_DETAIL}
        assert actual_public == PUBLIC_ROUTES
        assert (
            await client.get(api_route_path(HEALTH_PATH))
        ).status_code == status.HTTP_200_OK
        launcher.launch.assert_not_called()

    asyncio.run(run_scenario(services, scenario))


def test_two_accounts_isolate_every_resource_and_nested_reference(services):
    async def scenario(client, app, factory, redis, launcher):
        first = await signup(client)
        first_token = client.cookies.get(SESSION_COOKIE)
        graph = STARTER_NODE_GRAPH.model_dump(mode="json")
        template = (
            await client.post(
                api_route_path(GRAPH_TEMPLATES_PATH),
                json={"name": "Private graph", "graph": graph},
            )
        ).json()
        bot_body = {
            "definition_id": NODE_BASED_DEFINITION_ID,
            "inputs": {"name": "Private bot", "market_slugs": ["market"]},
            "graph_template_id": template["id"],
        }
        response = await client.post(api_route_path(BOTS_PATH), json=bot_body)
        assert response.status_code == status.HTTP_201_CREATED, response.text
        bot = response.json()
        revision = bot["latest_graph_revision"]
        run = (
            await client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]))
        ).json()
        assert len(launcher.launch.call_args_list) == 1
        # New account on a different client preserves the first user's session.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=ORIGIN, headers=HEADERS
        ) as second:
            await signup(second, "second@example.com")
            for path in [
                api_route_path(BOTS_PATH),
                api_route_path(RUNS_PATH),
                api_route_path(GRAPH_TEMPLATES_PATH),
            ]:
                assert (await second.get(path)).json() == []
            own_template = await second.post(
                api_route_path(GRAPH_TEMPLATES_PATH),
                json={"name": template["name"], "graph": graph},
            )
            assert own_template.status_code == status.HTTP_201_CREATED
            assert (
                await second.post(
                    api_route_path(GRAPH_TEMPLATES_PATH),
                    json={"name": template["name"], "graph": graph},
                )
            ).status_code == status.HTTP_409_CONFLICT
            foreign_paths = [
                ("GET", api_route_path(BOT_PATH, bot_id=bot["id"]), None),
                (
                    "PATCH",
                    api_route_path(BOT_PATH, bot_id=bot["id"]),
                    {"inputs": {"name": "stolen", "market_slugs": ["market"]}},
                ),
                (
                    "GET",
                    api_route_path(
                        BOT_GRAPH_REVISION_PATH,
                        bot_id=bot["id"],
                        revision_id=revision["id"],
                    ),
                    None,
                ),
                (
                    "POST",
                    api_route_path(BOT_GRAPH_REVISIONS_PATH, bot_id=bot["id"]),
                    {"graph": graph},
                ),
                ("POST", api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]), None),
                (
                    "GET",
                    api_route_path(GRAPH_TEMPLATE_PATH, template_id=template["id"]),
                    None,
                ),
                (
                    "PATCH",
                    api_route_path(GRAPH_TEMPLATE_PATH, template_id=template["id"]),
                    {"name": "stolen"},
                ),
                ("GET", api_route_path(RUN_PATH, run_id=run["id"]), None),
                ("POST", api_route_path(RUN_STOP_PATH, run_id=run["id"]), None),
                ("GET", api_route_path(RUN_EVENTS_PATH, run_id=run["id"]), None),
                ("GET", api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run["id"]), None),
            ]
            for method, path, body in foreign_paths:
                denied = await second.request(method, path, json=body)
                assert denied.status_code == status.HTTP_404_NOT_FOUND, (
                    path,
                    denied.text,
                )
                missing_path = (
                    path.replace(bot["id"], str(uuid4()))
                    .replace(template["id"], str(uuid4()))
                    .replace(run["id"], str(uuid4()))
                )
                missing = await second.request(method, missing_path, json=body)
                assert (denied.status_code, denied.json()) == (
                    missing.status_code,
                    missing.json(),
                )
            assert (
                await second.post(api_route_path(BOTS_PATH), json=bot_body)
            ).status_code == status.HTTP_404_NOT_FOUND
            spoof = await second.post(
                api_route_path(BOTS_PATH),
                json={**bot_body, "owner_user_id": first.json()["id"]},
            )
            assert spoof.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
            own_bot = (
                await second.post(
                    api_route_path(BOTS_PATH),
                    json={**bot_body, "graph_template_id": own_template.json()["id"]},
                )
            ).json()
            assert (
                await second.get(
                    api_route_path(
                        BOT_GRAPH_REVISION_PATH,
                        bot_id=own_bot["id"],
                        revision_id=revision["id"],
                    )
                )
            ).status_code == status.HTTP_404_NOT_FOUND
            assert len(launcher.launch.call_args_list) == 1
        assert (
            await client.patch(
                api_route_path(BOT_PATH, bot_id=bot["id"]),
                json={"inputs": {"name": "edited", "market_slugs": ["market"]}},
            )
        ).status_code == status.HTTP_200_OK
        assert (
            await client.post(
                api_route_path(BOT_GRAPH_REVISIONS_PATH, bot_id=bot["id"]),
                json={"graph": graph},
            )
        ).status_code == status.HTTP_201_CREATED
        assert (await client.get(api_route_path(RUN_PATH, run_id=run["id"]))).json()[
            "config"
        ]["name"] == "Private bot"
        # Authorized worker execution continues after logout.
        await client.post(api_route_path(LOGOUT_PATH))
        async with factory() as session:
            claimed = await RunStore(session).claim(run["id"], now=system_now_utc())
            assert claimed is not None and claimed.status is RunStatus.STARTING
        logged_in = await client.post(
            api_route_path(LOGIN_PATH),
            json={"email": first.json()["email"], "password": PASSWORD},
        )
        assert logged_in.status_code == status.HTTP_200_OK
        assert (
            await client.post(api_route_path(RUN_STOP_PATH, run_id=run["id"]))
        ).status_code == status.HTTP_200_OK
        assert (
            await client.get(api_route_path(RUN_EVENTS_PATH, run_id=run["id"]))
        ).status_code == status.HTTP_200_OK
        async with factory() as session:
            owner = (await session.execute(select(BotRow))).scalars().first()
            assert owner.owner_user_id is not None
            assert OWNER_USER_ID_COLUMN not in RunRow.model_fields
            assert (
                await AuthStore(session).current_user(SessionToken.parse(first_token))
                is None
            )

    asyncio.run(run_scenario(services, scenario))


def test_concurrent_equivalent_signup_has_one_user(services):
    async def scenario(client, app, factory, redis, launcher):
        async def attempt(email):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=ORIGIN, headers=HEADERS
            ) as separate:
                return await separate.post(
                    api_route_path(REGISTER_PATH),
                    json={"email": email, "password": PASSWORD},
                )

        responses = await asyncio.gather(
            attempt("Race@example.com"), attempt(" race@EXAMPLE.COM ")
        )
        assert sorted(response.status_code for response in responses) == [
            status.HTTP_201_CREATED,
            status.HTTP_409_CONFLICT,
        ]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(UserRow)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(SessionRow)) == 1
            )

    asyncio.run(run_scenario(services, scenario))


def test_stream_authorization_stops_after_logout_within_bound(services):
    async def scenario(client, app, factory, redis, launcher):
        user = (await signup(client)).json()
        token = client.cookies.get(SESSION_COOKIE)
        authorization = StreamAuthorization(
            factory, SessionToken.parse(token), UUID(user["id"])
        )
        with patch("api.auth.streams.monotonic", return_value=0):
            assert await authorization.allowed()
        await client.post(api_route_path(LOGOUT_PATH))
        with patch("api.auth.streams.monotonic", return_value=SESSION_RECHECK_SECONDS):
            assert not await authorization.allowed()
        # Guarded streaming cannot read history or subscribe after revocation.
        streamer = RunEventStreamer(uuid4(), AsyncMock(), factory, redis, authorization)
        with patch.object(RunEventReplay, "read", AsyncMock()) as reads:
            assert [frame async for frame in streamer.stream(FIRST_EVENT_CURSOR)] == []
            reads.assert_not_called()

    asyncio.run(run_scenario(services, scenario))


@pytest.mark.parametrize("legacy_table", [BOTS_TABLE_NAME, GRAPH_TEMPLATES_TABLE_NAME])
def test_migration_refuses_implicit_backfill_and_preserves_pre_auth_data(
    services, legacy_table
):
    url, _ = services
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "0004")

    async def seed_or_clear(*, clear=False):
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                if clear:
                    assert (
                        await connection.scalar(
                            text(f"SELECT count(*) FROM {legacy_table}")
                        )
                        == 1
                    )
                    await connection.execute(text(f"DELETE FROM {legacy_table}"))
                elif legacy_table == GRAPH_TEMPLATES_TABLE_NAME:
                    await connection.execute(
                        text(
                            f"INSERT INTO {GRAPH_TEMPLATES_TABLE_NAME} (id, name, graph, created_at, updated_at) VALUES (:id, 'legacy', '{{}}', now(), now())"
                        ),
                        {"id": uuid4()},
                    )
                else:
                    await connection.execute(
                        text(
                            "INSERT INTO bots (id, definition_id, config, created_at, updated_at) VALUES (:id, 'legacy', '{}', now(), now())"
                        ),
                        {"id": uuid4()},
                    )
        finally:
            await engine.dispose()

    asyncio.run(seed_or_clear())
    with pytest.raises(
        RuntimeError, match="explicitly authorized pre-auth alpha database reset"
    ):
        command.upgrade(config, "head")
    asyncio.run(seed_or_clear(clear=True))
    command.upgrade(config, "head")


def test_authenticated_database_failure_is_closed_and_secret_safe(services):
    async def scenario(client, app, factory, redis, launcher):
        await signup(client)
        with patch(
            "api.auth.store.AuthStore.current_user",
            AsyncMock(
                side_effect=OperationalError(
                    "private query", {}, Exception("private database detail")
                )
            ),
        ):
            response = await client.get(api_route_path(BOTS_PATH))
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            assert "private" not in response.text
        assert not launcher.launch.called

    asyncio.run(run_scenario(services, scenario))


def test_https_cookie_and_explicit_local_http_exception(services):
    with pytest.raises(ValueError, match="explicit local"):
        AuthSettings("http://localhost:5173")

    async def scenario(client, app, factory, redis, launcher):
        app.state.auth_settings = AuthSettings("https://paper.example.com")
        response = await client.post(
            api_route_path(REGISTER_PATH),
            json={"email": "secure@example.com", "password": PASSWORD},
            headers={"Origin": "https://paper.example.com"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "Secure" in response.headers["set-cookie"]
        assert "Domain=" not in response.headers["set-cookie"]

    asyncio.run(run_scenario(services, scenario))


def test_open_idle_stream_closes_after_logout_and_releases_redis(services):
    async def scenario(client, app, factory, redis, launcher):
        user = (await signup(client)).json()
        authorization = StreamAuthorization(
            factory,
            SessionToken.parse(client.cookies.get(SESSION_COOKIE)),
            UUID(user["id"]),
        )
        request = AsyncMock()
        request.is_disconnected.return_value = False
        pubsub = redis.pubsub()
        streamer = RunEventStreamer(uuid4(), request, factory, redis, authorization)
        with (
            patch.object(redis, "pubsub", return_value=pubsub),
            patch.object(RunEventReplay, "read", AsyncMock(return_value=())),
        ):
            stream = streamer.stream(FIRST_EVENT_CURSOR)
            with patch("api.auth.streams.monotonic", return_value=0):
                assert await anext(stream)
            assert pubsub.subscribed
            await client.post(api_route_path(LOGOUT_PATH))
            with patch(
                "api.auth.streams.monotonic", return_value=SESSION_RECHECK_SECONDS
            ):
                assert [frame async for frame in stream] == []
            assert not pubsub.subscribed

    asyncio.run(run_scenario(services, scenario))


def test_login_rotates_an_active_cookie_and_revokes_its_old_token(services):
    async def scenario(client, app, factory, redis, launcher):
        created = await signup(client)
        old_token = client.cookies.get(SESSION_COOKIE)
        response = await client.post(
            api_route_path(LOGIN_PATH),
            json={
                "email": created.json()["email"],
                "password": PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_200_OK
        new_token = client.cookies.get(SESSION_COOKIE)
        assert new_token != old_token
        assert (
            await client.get(api_route_path(ME_PATH))
        ).status_code == status.HTTP_200_OK
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=ORIGIN,
            cookies={SESSION_COOKIE: old_token},
        ) as stale:
            assert (
                await stale.get(api_route_path(ME_PATH))
            ).status_code == status.HTTP_401_UNAUTHORIZED
        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(SessionRow)) == 1
            )

    asyncio.run(run_scenario(services, scenario))


def test_login_quota_is_shared_across_instances_and_separate_from_signup(services):
    async def scenario(client, app, factory, redis, launcher):
        other = create_app(
            session_factory=factory,
            redis=redis,
            auth_settings=AuthSettings(ORIGIN, True),
        )
        body = {"email": "unknown@example.com", "password": PASSWORD}
        async with AsyncClient(
            transport=ASGITransport(app=other), base_url=ORIGIN, headers=HEADERS
        ) as second:
            for attempt in range(LOGIN_ATTEMPT_LIMIT):
                chosen = client if attempt % 2 else second
                assert (
                    await chosen.post(api_route_path(LOGIN_PATH), json=body)
                ).status_code == status.HTTP_401_UNAUTHORIZED
            limited = await second.post(api_route_path(LOGIN_PATH), json=body)
            assert limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            assert int(limited.headers[RETRY_AFTER_HEADER]) > 0
        assert (await signup(client)).status_code == status.HTTP_201_CREATED

    asyncio.run(run_scenario(services, scenario))


def test_replay_stops_before_the_next_frame_after_session_revocation(services):
    async def scenario(client, app, factory, redis, launcher):
        user = (await signup(client)).json()
        token = SessionToken.parse(client.cookies.get(SESSION_COOKIE))
        authorization = StreamAuthorization(factory, token, UUID(user["id"]))
        run_id = uuid4()
        events = tuple(
            RunLifecycleEvent(
                id=event_id,
                run_id=run_id,
                occurred_at=system_now_utc(),
                payload=RunStatusPayload(status=RunStatus.RUNNING),
            )
            for event_id in (1, 2)
        )
        streamer = RunEventStreamer(run_id, AsyncMock(), factory, redis, authorization)
        with patch.object(RunEventReplay, "read", AsyncMock(return_value=events)):
            stream = streamer.stream(FIRST_EVENT_CURSOR)
            with patch("api.auth.streams.monotonic", return_value=0):
                assert "id: 1" in await anext(stream)
            await client.post(api_route_path(LOGOUT_PATH))
            with patch(
                "api.auth.streams.monotonic", return_value=SESSION_RECHECK_SECONDS
            ):
                assert [frame async for frame in stream] == []

    asyncio.run(run_scenario(services, scenario))


def test_corrupt_password_hash_is_unavailable_without_leaking_persisted_state(services):
    async def scenario(client, app, factory, redis, launcher):
        created = await signup(client)
        async with factory() as session:
            await session.execute(
                update(UserRow).values(password_hash="private corrupt hash")
            )
            await session.commit()
        response = await client.post(
            api_route_path(LOGIN_PATH),
            json={
                "email": created.json()["email"],
                "password": PASSWORD,
            },
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "private corrupt hash" not in response.text
        assert PASSWORD not in response.text

    asyncio.run(run_scenario(services, scenario))


def test_identity_migration_matches_metadata_and_downgrades_cleanly(services):
    url, _ = services

    async def check_schema():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:

                def compare(sync_connection):
                    inspector = inspect(sync_connection)
                    for model in (UserRow, SessionRow, BotRow, GraphTemplateRow):
                        table = model.__table__
                        actual = {
                            column["name"]: column
                            for column in inspector.get_columns(table.name)
                        }
                        assert set(actual) == set(table.columns.keys())
                        for column in table.columns:
                            assert actual[column.name]["nullable"] == column.nullable
                            assert str(
                                actual[column.name]["type"].compile(
                                    dialect=sync_connection.dialect
                                )
                            ) == str(
                                column.type.compile(dialect=sync_connection.dialect)
                            )
                        actual_unique = {
                            tuple(item["column_names"])
                            for item in inspector.get_unique_constraints(table.name)
                        }
                        expected_unique = {
                            tuple(column.name for column in item.columns)
                            for item in table.constraints
                            if isinstance(item, UniqueConstraint)
                        }
                        assert actual_unique == expected_unique
                        assert {
                            tuple(item["column_names"])
                            for item in inspector.get_indexes(table.name)
                            if not item.get("duplicates_constraint")
                        } == {
                            tuple(column.name for column in item.columns)
                            for item in table.indexes
                        }
                        actual_foreign = {
                            (
                                tuple(item["constrained_columns"]),
                                item["referred_table"],
                                tuple(item["referred_columns"]),
                            )
                            for item in inspector.get_foreign_keys(table.name)
                        }
                        expected_foreign = {
                            (
                                tuple(element.parent.name for element in item.elements),
                                item.referred_table.name,
                                tuple(element.column.name for element in item.elements),
                            )
                            for item in table.foreign_key_constraints
                        }
                        assert actual_foreign == expected_foreign

                await connection.run_sync(compare)
        finally:
            await engine.dispose()

    asyncio.run(check_schema())
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "0004")

    async def check_downgrade():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                for table in (USERS_TABLE, SESSIONS_TABLE):
                    assert (
                        await connection.scalar(
                            text("SELECT to_regclass(:table)"), {"table": table}
                        )
                        is None
                    )
                for table in (BOTS_TABLE_NAME, GRAPH_TEMPLATES_TABLE_NAME):
                    columns = await connection.run_sync(
                        lambda sync: inspect(sync).get_columns(table)
                    )
                    assert OWNER_USER_ID_COLUMN not in {
                        column["name"] for column in columns
                    }
        finally:
            await engine.dispose()

    asyncio.run(check_downgrade())
    command.upgrade(config, "head")
