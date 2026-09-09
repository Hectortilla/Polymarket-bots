"""Forward migration retains old credentials, sessions and unverified access."""

import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from api.auth.models import UserRow
from api.auth.passwords import HASHER
from api.auth.policy import LOGIN_PATH, ME_PATH, SESSION_COOKIE
from api.auth.recovery.contracts import AccountStatus
from api.auth.recovery.models import AccountTokenRow
from api.auth.recovery.policy import ACCOUNT_PATH
from api.auth.schema import SESSIONS_TABLE, USERS_TABLE, SessionColumn, UserColumn
from api.auth.store.tokens import SessionToken
from api.catalog.definitions import WINNER_DEFINITION_ID
from api.http.routes.paths import BOT_RUNS_PATH, BOTS_PATH, api_route_path
from fastapi import status
from polybot.framework.clock import system_now_utc
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from control_plane.test_auth import PASSWORD, run_scenario
from control_plane.test_auth import services as services


def test_forward_migration_preserves_unverified_existing_accounts(services):
    url, _ = services
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "0006")
    user_id = uuid4()
    token = SessionToken.issue()
    now = system_now_utc()
    password_hash = HASHER.hash(PASSWORD)

    async def seed():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f"INSERT INTO {USERS_TABLE} ({UserColumn.ID},{UserColumn.EMAIL},{UserColumn.PASSWORD_HASH},{UserColumn.CREATED_AT}) VALUES (:id,'legacy@example.com',:hash,:now)"
                ),
                {"id": user_id, "now": now, "hash": password_hash},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {SESSIONS_TABLE} ({SessionColumn.TOKEN_DIGEST},{SessionColumn.USER_ID},{SessionColumn.CREATED_AT},{SessionColumn.EXPIRES_AT}) VALUES (:token,:id,:now,:expires)"
                ),
                {
                    "token": token.digest,
                    "id": user_id,
                    "now": now,
                    "expires": now + timedelta(days=1),
                },
            )
        await engine.dispose()

    asyncio.run(seed())
    command.upgrade(config, "head")

    async def verify():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        text(f"SELECT * FROM {USERS_TABLE} WHERE {UserColumn.ID}=:id"),
                        {"id": user_id},
                    )
                )
                .mappings()
                .one()
            )
            assert (
                row[UserColumn.EMAIL_VERIFIED_AT] is None
                and row[UserColumn.VERIFICATION_REQUIRED] is False
            )
            assert row[UserColumn.PASSWORD_HASH] == password_hash
            assert (
                await connection.scalar(
                    text(
                        f"SELECT count(*) FROM {SESSIONS_TABLE} WHERE {SessionColumn.TOKEN_DIGEST}=:token"
                    ),
                    {"token": token.digest},
                )
                == 1
            )
            await connection.execute(
                text(
                    f"INSERT INTO {USERS_TABLE} ({UserColumn.ID},{UserColumn.EMAIL},{UserColumn.PASSWORD_HASH},{UserColumn.CREATED_AT}) VALUES (:id,'new@example.com','hash',:now)"
                ),
                {"id": uuid4(), "now": now},
            )
            assert (
                await connection.scalar(
                    text(
                        f"SELECT {UserColumn.VERIFICATION_REQUIRED} FROM {USERS_TABLE} WHERE {UserColumn.EMAIL}='new@example.com'"
                    )
                )
                is True
            )
            for model in (UserRow, AccountTokenRow):
                columns = await connection.run_sync(
                    lambda sync: inspect(sync).get_columns(model.__tablename__)
                )
                assert {column["name"] for column in columns} == set(
                    model.__table__.columns.keys()
                )
        await engine.dispose()

    asyncio.run(verify())

    async def legacy_access(client, app, factory, redis, launcher):
        client.cookies.set(SESSION_COOKIE, token.value)
        assert (await client.get(api_route_path(ME_PATH))).json()["id"] == str(user_id)
        assert (await client.get(api_route_path(ACCOUNT_PATH))).json() == AccountStatus(
            email_verified=False, verification_required=False
        ).model_dump()
        assert (
            await client.post(
                api_route_path(LOGIN_PATH),
                json={"email": "legacy@example.com", "password": PASSWORD},
            )
        ).status_code == status.HTTP_200_OK
        bot = (
            await client.post(
                api_route_path(BOTS_PATH),
                json={
                    "definition_id": WINNER_DEFINITION_ID,
                    "inputs": {"name": "migrated account"},
                },
            )
        ).json()
        assert (
            await client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]))
        ).status_code == status.HTTP_202_ACCEPTED

    asyncio.run(run_scenario(services, legacy_access))
