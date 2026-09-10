"""The initial migration is complete and repeat upgrades preserve account history."""

import asyncio
from io import StringIO
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from api.auth.models import UserRow
from api.auth.schema import USERS_TABLE, UserColumn
from api.bots.models import BotRow
from api.events.store import EventStore
from api.operations.models import OperationControlRow
from api.operations.schema import (
    DEFAULT_ADMISSIONS_PAUSED,
    GLOBAL_OPERATION_CONTROL_ROW_ID,
)
from api.runs.models import RunRow
from api.runs.store import RunStore
from polybot.framework.clock import system_now_utc
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select

from control_plane.limits_fixtures import account_bot, queue_run, resource_services
from control_plane.limits_fixtures import limits_services as limits_services


def test_repeated_upgrade_preserves_accounts_and_terminal_history(limits_services):
    async def seed():
        async with resource_services(limits_services) as (sessions, redis):
            user, bot = await account_bot(sessions)
            run = await queue_run(sessions, bot)
            async with sessions() as session:
                await RunStore(session).request_stop(run.id, now=system_now_utc())
                events = await EventStore(session).read(run.id)
                return user.id, run.id, events

    user_id, run_id, events = asyncio.run(seed())
    config = Config(Path(__file__).parents[2] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", limits_services[0])
    command.upgrade(config, "head")

    async def verify():
        async with resource_services(limits_services) as (sessions, redis):
            async with sessions() as session:
                assert await session.get(UserRow, user_id) is not None
                row = await session.get(RunRow, run_id)
                assert (await session.get(BotRow, row.bot_id)).deleted_at is None
                assert (
                    row.launch_key
                    is row.execution_token
                    is row.delivery_attempted_at
                    is None
                )
                assert await EventStore(session).read(run_id) == events

    asyncio.run(verify())


def test_initial_revision_is_the_only_head_and_supports_offline_sql():
    output = StringIO()
    config = Config(Path(__file__).parents[2] / "alembic.ini", output_buffer=output)
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())
    assert [item.revision for item in revisions] == ["0001"]
    assert revisions[0].down_revision is None
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://")
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE" in sql
    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql


def test_initial_schema_seeds_required_defaults(limits_services):
    async def verify():
        async with resource_services(limits_services) as (sessions, redis):
            async with sessions() as session:
                controls = (
                    (await session.execute(select(OperationControlRow))).scalars().all()
                )
                assert len(controls) == 1
                assert controls[0].id == GLOBAL_OPERATION_CONTROL_ROW_ID
                assert controls[0].admissions_paused is DEFAULT_ADMISSIONS_PAUSED
                # Bypass Python model defaults to exercise the database default.
                row = (
                    await session.execute(
                        text(
                            f"INSERT INTO {USERS_TABLE} "
                            f"({UserColumn.ID}, {UserColumn.EMAIL}, {UserColumn.PASSWORD_HASH}, {UserColumn.CREATED_AT}) "
                            f"VALUES (:id, :email, :password_hash, :now) "
                            f"RETURNING {UserColumn.VERIFICATION_REQUIRED}, {UserColumn.EMAIL_VERIFIED_AT}"
                        ),
                        {
                            "id": uuid4(),
                            "email": "initial@example.com",
                            "password_hash": "fixture",
                            "now": system_now_utc(),
                        },
                    )
                ).one()
                assert row.verification_required is True
                assert row.email_verified_at is None

    asyncio.run(verify())


def test_initial_schema_matches_metadata(limits_services):
    url, _ = limits_services

    async def check_schema():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:

                def compare(sync_connection):
                    inspector = inspect(sync_connection)
                    assert set(inspector.get_table_names()) == set(
                        SQLModel.metadata.tables
                    ) | {"alembic_version"}
                    for table in SQLModel.metadata.sorted_tables:
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
                        assert inspector.get_pk_constraint(table.name)[
                            "constrained_columns"
                        ] == [column.name for column in table.primary_key.columns]
                        assert {
                            item["name"]
                            for item in inspector.get_check_constraints(table.name)
                        } == {
                            item.name
                            for item in table.constraints
                            if isinstance(item, CheckConstraint)
                        }
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
