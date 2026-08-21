from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.sql.elements import TextClause

from polybot.framework.streams import StreamRelation
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    INITIAL_DEFINITION_VERSION,
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
)
from polybot_control_plane.runs.contracts import RunRead, RunStatus
from polybot_control_plane.runs.models import RunRow
from polybot_control_plane.runs.schema import (
    DEFINITION_VERSION_CONSTRAINT_NAME,
    RunColumn,
    RUNS_TABLE_NAME,
    RUN_STATUS_CONSTRAINT_NAME,
)
from polybot_control_plane.runs.store import RunStore


TEST_POSTGRES_URL_ENV = "POLYBOT_TEST_POSTGRES_URL"
POSTGRES_NOT_CONFIGURED_SKIP_REASON = (
    f"{TEST_POSTGRES_URL_ENV} is not configured"
)
PROJECT_ROOT = Path(__file__).parents[2]


def _postgres_url() -> str:
    url = os.getenv(TEST_POSTGRES_URL_ENV)
    if url is None:
        pytest.skip(POSTGRES_NOT_CONFIGURED_SKIP_REASON)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _alembic_config(url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def _run_insert_statement() -> TextClause:
    columns = ", ".join(column.value for column in RunColumn)
    values = ", ".join(
        (
            f"CAST(:{column.value} AS JSONB)"
            if column is RunColumn.CONFIG
            else f":{column.value}"
        )
        for column in RunColumn
    )
    return text(
        f"INSERT INTO {RUNS_TABLE_NAME} ({columns}) VALUES ({values})"
    )


@pytest.mark.postgres
def test_migration_upgrades_and_downgrades_exact_run_columns() -> None:
    url = _postgres_url()
    config = _alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    async def inspect_upgrade() -> tuple[
        list[str],
        list[dict[str, object]],
        list[dict[str, object]],
        dict[str, object],
    ]:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
            columns = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_columns(
                    RUNS_TABLE_NAME
                )
            )
            checks = await connection.run_sync(
                lambda sync_connection: inspect(
                    sync_connection
                ).get_check_constraints(RUNS_TABLE_NAME)
            )
            primary_key = await connection.run_sync(
                lambda sync_connection: inspect(
                    sync_connection
                ).get_pk_constraint(RUNS_TABLE_NAME)
            )
        await engine.dispose()
        return table_names, columns, checks, primary_key

    table_names, columns, checks, primary_key = asyncio.run(inspect_upgrade())

    assert RUNS_TABLE_NAME in table_names
    assert tuple(column["name"] for column in columns) == tuple(
        RunRow.__table__.columns.keys()
    )
    database_columns = {column["name"]: column for column in columns}
    dialect = postgresql.dialect()
    for model_column in RunRow.__table__.columns:
        database_column = database_columns[model_column.name]
        assert database_column["type"].compile(dialect=dialect) == (
            model_column.type.compile(dialect=dialect)
        )
        assert database_column["nullable"] is model_column.nullable
    assert primary_key["constrained_columns"] == [RunRow.id.name]
    assert {check["name"] for check in checks} == {
        DEFINITION_VERSION_CONSTRAINT_NAME,
        RUN_STATUS_CONSTRAINT_NAME,
    }

    async def assert_constraint_rejections() -> None:
        engine = create_async_engine(url)
        statement = _run_insert_statement()
        common_values = {
            RunColumn.DEFINITION_ID.value: "definition",
            RunColumn.DEFINITION_VERSION.value: INITIAL_DEFINITION_VERSION,
            RunColumn.CONFIG.value: json.dumps({}),
            RunColumn.STATUS.value: RunStatus.QUEUED.value,
            RunColumn.CREATED_AT.value: datetime.now(UTC),
        }
        invalid_rows = (
            {
                **common_values,
                RunColumn.ID.value: uuid4(),
                RunColumn.DEFINITION_VERSION.value: 0,
            },
            {
                **common_values,
                RunColumn.ID.value: uuid4(),
                RunColumn.STATUS.value: "unknown",
            },
        )
        for row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(statement, row)
        await engine.dispose()

    asyncio.run(assert_constraint_rejections())

    command.downgrade(config, "base")

    async def inspect_downgrade() -> list[str]:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
        await engine.dispose()
        return table_names

    table_names = asyncio.run(inspect_downgrade())

    assert RUNS_TABLE_NAME not in table_names


@pytest.mark.postgres
def test_run_store_round_trip_restores_typed_config_and_newest_first() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    config = CATALOG[WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID].parse_config(
        {
            "name": "first",
            "wallet_addresses": [
                "0x0000000000000000000000000000000000000001"
            ],
            "max_order_size": "3.250",
            "max_slippage_pct": "0.0150",
            "paper_portfolio_usdc": "1500.00",
        }
    )

    async def round_trip() -> tuple[
        RunRead,
        RunRead,
        RunRead | None,
        RunRead | None,
        tuple[RunRead, ...],
        tuple[RunRow, RunRow],
    ]:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            store = RunStore(session)
            first = await store.create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
                config=config,
            )
            second = await store.create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
                config=config.model_copy(update={"name": "second"}),
            )
            restored = await store.read(first.id)
            missing = await store.read(uuid4())
            tied_at = datetime.now(UTC)
            tied_rows = (
                RunRow(
                    id=uuid4(),
                    definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                    definition_version=INITIAL_DEFINITION_VERSION,
                    config=config.model_dump(mode="json"),
                    created_at=tied_at,
                ),
                RunRow(
                    id=uuid4(),
                    definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                    definition_version=INITIAL_DEFINITION_VERSION,
                    config=config.model_dump(mode="json"),
                    created_at=tied_at,
                ),
            )
            session.add_all(tied_rows)
            await session.commit()
            runs = await store.list()
        await engine.dispose()
        return first, second, restored, missing, runs, tied_rows

    try:
        first, second, restored, missing, runs, tied_rows = asyncio.run(
            round_trip()
        )
    finally:
        command.downgrade(alembic_config, "base")

    assert isinstance(restored, RunRead)
    assert restored.status is RunStatus.QUEUED
    assert restored.config.model_dump(mode="json") == config.model_dump(mode="json")
    assert restored.config.max_order_size.as_tuple() == config.max_order_size.as_tuple()
    assert restored.config.stream_rules[0].relation is StreamRelation.INDEPENDENT
    assert restored.config.stream_rules[0].wallet_addresses == (
        "0x0000000000000000000000000000000000000001",
    )
    assert missing is None
    run_ids = tuple(run.id for run in runs)
    assert tuple(
        run_id for run_id in run_ids if run_id in {first.id, second.id}
    ) == (second.id, first.id)
    assert tuple(
        run_id for run_id in run_ids if run_id in {row.id for row in tied_rows}
    ) == tuple(sorted((row.id for row in tied_rows), reverse=True))
