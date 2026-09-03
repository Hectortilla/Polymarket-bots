from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql.elements import TextClause
from sqlmodel import select

import polybot_control_plane.execution.worker.lifecycle as worker_lifecycle
import polybot_control_plane.execution.worker.resources as worker_resources
import polybot_control_plane.execution.worker.runtime as worker_runtime
from control_plane.graph_fixtures import threshold_buy_graph
from control_plane.service_config import (
    POSTGRES_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
)
from polybot.cli.observability.broker import ObservableBroker
from polybot.execution.broker import Broker
from polybot.framework.context import BotContext
from polybot.framework.events import FillEvent, FillRejectReason, Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.streams import StreamRelation
from polybot.performance.contracts.valuation_status import ValuationStatus
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    NODE_BASED_DEFINITION_ID,
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
    WINNER_DEFINITION_ID,
)
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.catalog.graphs.starter import STARTER_NODE_GRAPH
from polybot_control_plane.api.app import create_app
from polybot_control_plane.api.routes.paths import (
    BOT_RUNS_PATH,
    GRAPH_TEMPLATE_PATH,
    GRAPH_TEMPLATES_PATH,
    api_route_path,
)
from polybot_control_plane.bots.contracts import BotRead
from polybot_control_plane.bots.models import BotGraphRevisionRow, BotRow
from polybot_control_plane.bots.revisions import FIRST_GRAPH_REVISION_NUMBER
from polybot_control_plane.bots.schema import (
    BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME,
    BOT_GRAPH_REVISIONS_TABLE_NAME,
    BOTS_TABLE_NAME,
)
from polybot_control_plane.bots.store import BotStore
from polybot_control_plane.graph_templates.contracts import (
    GraphTemplateCreate,
    GraphTemplateUpdate,
)
from polybot_control_plane.graph_templates.models import GraphTemplateRow
from polybot_control_plane.graph_templates.schema import (
    GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME,
    GRAPH_TEMPLATES_TABLE_NAME,
)
from polybot_control_plane.graph_templates.store import GraphTemplateStore
from polybot_control_plane.database import DATABASE_URL_ENV, async_database_url
from polybot_control_plane.events.contracts import (
    BrokerFillEvent,
    BrokerOrderEvent,
    ChartSampleEvent,
    ChartSamplePayload,
    RunLifecycleEvent,
    RunStatusPayload,
)
from polybot_control_plane.events.kinds import EventKind
from polybot_control_plane.events.contracts.payloads import EquityChartPointPayload
from polybot_control_plane.events.models import EventRow
from polybot_control_plane.events.observer import WebRuntimeObserver
from polybot_control_plane.events.schema import (
    EVENT_KIND_CONSTRAINT_NAME,
    RUN_EVENTS_CURSOR_INDEX_NAME,
    RUN_EVENTS_RUN_ID_INDEX_NAME,
    RUN_EVENTS_TABLE_NAME,
    EventColumn,
)
from polybot_control_plane.events.store import EventStore
from polybot_control_plane.events.writer import RunEventWriter
from polybot_control_plane.execution.config import REDIS_URL_ENV
from polybot_control_plane.execution.worker import execute_run
from polybot_control_plane.execution.worker.lease import reconcile_expired_run
from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.status import RunStatus
from polybot_control_plane.runs.models import RunRow
from polybot_control_plane.runs.schema import (
    RUN_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    RUN_STATUS_CONSTRAINT_NAME,
    RUNS_TABLE_NAME,
    RunColumn,
)
from polybot_control_plane.runs.store import RunStore

PROJECT_ROOT = Path(__file__).parents[2]


def _postgres_url() -> str:
    url = os.getenv(TEST_POSTGRES_URL_ENV)
    if url is None:
        pytest.skip(POSTGRES_NOT_CONFIGURED_SKIP_REASON)
    return async_database_url(url).render_as_string(hide_password=False)


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


async def _create_run(
    session: AsyncSession,
    *,
    definition_id: str,
    config,
    graph: NodeGraph | None = None,
) -> RunRead:
    bot = await BotStore(session).create(
        definition_id=definition_id,
        config=config,
        graph=graph,
    )
    return await RunStore(session).create_from_bot(bot)


@pytest.mark.postgres
def test_migrations_upgrade_and_downgrade_event_schema_and_cursor_index() -> None:
    url = _postgres_url()
    config = _alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "0001")

    async def inspect_schema() -> tuple[
        list[str],
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, object]],
        dict[str, object],
        list[dict[str, object]],
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
            event_columns = []
            event_indexes = []
            event_checks = []
            event_foreign_keys = []
            event_primary_key = {}
            if RUN_EVENTS_TABLE_NAME in table_names:
                event_columns = await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_columns(
                        RUN_EVENTS_TABLE_NAME
                    )
                )
                event_indexes = await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_indexes(
                        RUN_EVENTS_TABLE_NAME
                    )
                )
                event_checks = await connection.run_sync(
                    lambda sync_connection: inspect(
                        sync_connection
                    ).get_check_constraints(RUN_EVENTS_TABLE_NAME)
                )
                event_foreign_keys = await connection.run_sync(
                    lambda sync_connection: inspect(
                        sync_connection
                    ).get_foreign_keys(RUN_EVENTS_TABLE_NAME)
                )
                event_primary_key = await connection.run_sync(
                    lambda sync_connection: inspect(
                        sync_connection
                    ).get_pk_constraint(RUN_EVENTS_TABLE_NAME)
                )
        await engine.dispose()
        return (
            table_names,
            columns,
            checks,
            primary_key,
            event_columns,
            event_indexes,
            event_checks,
            event_foreign_keys,
            event_primary_key,
        )

    slice_12a_schema = asyncio.run(inspect_schema())
    assert tuple(column["name"] for column in slice_12a_schema[1]) == tuple(
        column.value for column in RunColumn
    )
    assert RUN_EVENTS_TABLE_NAME not in slice_12a_schema[0]

    command.upgrade(config, "head")
    (
        table_names,
        columns,
        checks,
        primary_key,
        event_columns,
        event_indexes,
        event_checks,
        event_foreign_keys,
        event_primary_key,
    ) = asyncio.run(inspect_schema())

    assert RUNS_TABLE_NAME in table_names
    assert RUN_EVENTS_TABLE_NAME in table_names
    assert {
        GRAPH_TEMPLATES_TABLE_NAME,
        BOTS_TABLE_NAME,
        BOT_GRAPH_REVISIONS_TABLE_NAME,
    }.issubset(table_names)
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
    assert {check["name"] for check in checks} == {RUN_STATUS_CONSTRAINT_NAME}

    async def inspect_saved_bot_schema() -> dict[str, object]:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            def inspect_all(sync_connection):
                inspector = inspect(sync_connection)
                return {
                    "template_columns": inspector.get_columns(
                        GRAPH_TEMPLATES_TABLE_NAME
                    ),
                    "template_uniques": inspector.get_unique_constraints(
                        GRAPH_TEMPLATES_TABLE_NAME
                    ),
                    "bot_columns": inspector.get_columns(BOTS_TABLE_NAME),
                    "revision_columns": inspector.get_columns(
                        BOT_GRAPH_REVISIONS_TABLE_NAME
                    ),
                    "revision_checks": inspector.get_check_constraints(
                        BOT_GRAPH_REVISIONS_TABLE_NAME
                    ),
                    "revision_uniques": inspector.get_unique_constraints(
                        BOT_GRAPH_REVISIONS_TABLE_NAME
                    ),
                    "run_foreign_keys": inspector.get_foreign_keys(
                        RUNS_TABLE_NAME
                    ),
                }

            result = await connection.run_sync(inspect_all)
        await engine.dispose()
        return result

    saved_bot_schema = asyncio.run(inspect_saved_bot_schema())
    assert tuple(
        column["name"] for column in saved_bot_schema["template_columns"]
    ) == tuple(GraphTemplateRow.__table__.columns.keys())
    assert tuple(
        column["name"] for column in saved_bot_schema["bot_columns"]
    ) == tuple(BotRow.__table__.columns.keys())
    assert tuple(
        column["name"] for column in saved_bot_schema["revision_columns"]
    ) == tuple(BotGraphRevisionRow.__table__.columns.keys())
    assert {
        constraint["name"] for constraint in saved_bot_schema["template_uniques"]
    } == {GRAPH_TEMPLATE_NAME_CONSTRAINT_NAME}
    assert {
        constraint["name"] for constraint in saved_bot_schema["revision_checks"]
    } == {BOT_GRAPH_REVISION_NUMBER_CONSTRAINT_NAME}
    assert {
        constraint["name"] for constraint in saved_bot_schema["revision_uniques"]
    } == {
        BOT_GRAPH_REVISION_SEQUENCE_CONSTRAINT_NAME,
        BOT_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME,
    }
    run_foreign_keys = saved_bot_schema["run_foreign_keys"]
    assert any(
        foreign_key["name"] == RUN_GRAPH_REVISION_OWNERSHIP_CONSTRAINT_NAME
        and foreign_key["constrained_columns"]
        == [RunColumn.BOT_ID, RunColumn.BOT_GRAPH_REVISION_ID]
        for foreign_key in run_foreign_keys
    )
    assert tuple(column["name"] for column in event_columns) == tuple(
        EventRow.__table__.columns.keys()
    )
    event_database_columns = {column["name"]: column for column in event_columns}
    for model_column in EventRow.__table__.columns:
        database_column = event_database_columns[model_column.name]
        assert database_column["type"].compile(dialect=dialect) == (
            model_column.type.compile(dialect=dialect)
        )
        assert database_column["nullable"] is model_column.nullable
    assert event_primary_key["constrained_columns"] == [EventRow.id.name]
    assert {index["name"] for index in event_indexes} == {
        RUN_EVENTS_CURSOR_INDEX_NAME
    }
    assert event_indexes[0]["column_names"] == [
        EventRow.run_id.name,
        EventRow.id.name,
    ]
    assert {check["name"] for check in event_checks} == {
        EVENT_KIND_CONSTRAINT_NAME
    }
    assert EventKind.CHART_SAMPLE.value in event_checks[0]["sqltext"]
    assert len(event_foreign_keys) == 1
    assert event_foreign_keys[0]["constrained_columns"] == [EventRow.run_id.name]
    assert event_foreign_keys[0]["referred_table"] == RUNS_TABLE_NAME
    assert event_foreign_keys[0]["referred_columns"] == [RunRow.id.name]

    async def assert_constraint_rejections() -> None:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            bot = await BotStore(session).create(
                definition_id=WINNER_DEFINITION_ID,
                config=CATALOG[WINNER_DEFINITION_ID].parse_config(
                    {"name": "constraint"}
                ),
                graph=None,
            )
        statement = _run_insert_statement()
        common_values = {
            RunColumn.BOT_ID.value: bot.id,
            RunColumn.DEFINITION_ID.value: "definition",
            RunColumn.CONFIG.value: json.dumps({}),
            RunColumn.BOT_GRAPH_REVISION_ID.value: None,
            RunColumn.STATUS.value: RunStatus.QUEUED.value,
            RunColumn.CREATED_AT.value: datetime.now(UTC),
            RunColumn.STARTED_AT.value: None,
            RunColumn.ENDED_AT.value: None,
            RunColumn.HEARTBEAT_AT.value: None,
            RunColumn.FAILURE_DETAIL.value: None,
        }
        invalid_rows = ({
            **common_values,
            RunColumn.ID.value: uuid4(),
            RunColumn.STATUS.value: "unknown",
        },)
        for row in invalid_rows:
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(statement, row)
        await engine.dispose()

    asyncio.run(assert_constraint_rejections())

    async def insert_chart_sample(*, accepted: bool) -> None:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            bot = await BotStore(session).create(
                definition_id=WINNER_DEFINITION_ID,
                config=CATALOG[WINNER_DEFINITION_ID].parse_config(
                    {"name": "chart-sample"}
                ),
                graph=None,
            )
        run_id = uuid4()
        run_values = {
            RunColumn.ID.value: run_id,
            RunColumn.BOT_ID.value: bot.id,
            RunColumn.DEFINITION_ID.value: "definition",
            RunColumn.CONFIG.value: json.dumps({}),
            RunColumn.BOT_GRAPH_REVISION_ID.value: None,
            RunColumn.STATUS.value: RunStatus.QUEUED.value,
            RunColumn.CREATED_AT.value: datetime.now(UTC),
            RunColumn.STARTED_AT.value: None,
            RunColumn.ENDED_AT.value: None,
            RunColumn.HEARTBEAT_AT.value: None,
            RunColumn.FAILURE_DETAIL.value: None,
        }
        event_statement = text(
            f"INSERT INTO {RUN_EVENTS_TABLE_NAME} "
            f"({EventColumn.RUN_ID}, {EventColumn.KIND}, "
            f"{EventColumn.OCCURRED_AT}, {EventColumn.PAYLOAD}) "
            "VALUES (:run_id, :kind, :occurred_at, CAST(:payload AS JSONB))"
        )

        async def insert() -> None:
            async with engine.begin() as connection:
                await connection.execute(_run_insert_statement(), run_values)
                await connection.execute(
                    event_statement,
                    {
                        "run_id": run_id,
                        "kind": EventKind.CHART_SAMPLE.value,
                        "occurred_at": datetime.now(UTC),
                        "payload": json.dumps({}),
                    },
                )
                await connection.execute(
                    event_statement,
                    {
                        "run_id": run_id,
                        "kind": EventKind.RUN_LIFECYCLE.value,
                        "occurred_at": datetime.now(UTC),
                        "payload": json.dumps({}),
                    },
                )

        if accepted:
            await insert()
        else:
            with pytest.raises(IntegrityError):
                await insert()
        await engine.dispose()

    asyncio.run(insert_chart_sample(accepted=True))

    command.downgrade(config, "0002")

    async def persisted_event_kinds() -> tuple[str, ...]:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            kinds = (
                await connection.execute(
                    text(
                        f"SELECT {EventColumn.KIND} "
                        f"FROM {RUN_EVENTS_TABLE_NAME} "
                        f"ORDER BY {EventColumn.ID}"
                    )
                )
            ).scalars()
            result = tuple(kinds)
        await engine.dispose()
        return result

    slice_12b_schema = asyncio.run(inspect_schema())
    assert {index["name"] for index in slice_12b_schema[5]} == {
        RUN_EVENTS_RUN_ID_INDEX_NAME
    }
    assert slice_12b_schema[5][0]["column_names"] == [EventRow.run_id.name]
    assert EventKind.CHART_SAMPLE.value not in slice_12b_schema[6][0]["sqltext"]
    assert asyncio.run(persisted_event_kinds()) == (
        EventKind.RUN_LIFECYCLE.value,
    )
    asyncio.run(insert_chart_sample(accepted=False))

    command.downgrade(config, "0001")
    downgraded_schema = asyncio.run(inspect_schema())
    assert RUN_EVENTS_TABLE_NAME not in downgraded_schema[0]
    assert tuple(column["name"] for column in downgraded_schema[1]) == tuple(
        column.value for column in RunColumn
    )
    command.downgrade(config, "base")


@pytest.mark.postgres
def test_run_store_round_trip_restores_typed_config_and_newest_first() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    definition_id = NODE_BASED_DEFINITION_ID
    graph_snapshot = threshold_buy_graph()
    expected_graph = NodeGraph.model_validate(graph_snapshot)
    config = CATALOG[definition_id].parse_config(
        {
            "name": "first",
            "market_slugs": ["example-market"],
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
            first = await _create_run(session,
                definition_id=definition_id,
                config=config,
                graph=expected_graph,
            )
            second = await _create_run(session,
                definition_id=definition_id,
                config=config.model_copy(update={"name": "second"}),
                graph=expected_graph,
            )
            restored = await store.read(first.id)
            missing = await store.read(uuid4())
            tied_at = datetime.now(UTC)
            tied_rows = (
                RunRow(
                    id=uuid4(),
                    bot_id=first.bot_id,
                    definition_id=definition_id,
                    config=config.model_dump(mode="json"),
                    bot_graph_revision_id=first.bot_graph_revision_id,
                    created_at=tied_at,
                ),
                RunRow(
                    id=uuid4(),
                    bot_id=first.bot_id,
                    definition_id=definition_id,
                    config=config.model_dump(mode="json"),
                    bot_graph_revision_id=first.bot_graph_revision_id,
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
    assert restored.config.stream_rules[0].market_slugs == ("example-market",)
    assert restored.graph == expected_graph
    assert missing is None
    run_ids = tuple(run.id for run in runs)
    assert tuple(
        run_id for run_id in run_ids if run_id in {first.id, second.id}
    ) == (second.id, first.id)
    assert tuple(
        run_id for run_id in run_ids if run_id in {row.id for row in tied_rows}
    ) == tuple(sorted((row.id for row in tied_rows), reverse=True))


@pytest.mark.postgres
def test_template_bot_revision_and_run_snapshots_are_isolated() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    updated_graph = NodeGraph.model_validate(threshold_buy_graph())
    config = CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
        {"name": "isolated", "market_slugs": ["example-market"]}
    )

    async def scenario() -> None:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            template_store = GraphTemplateStore(session)
            template = await template_store.create(
                GraphTemplateCreate(name="Reusable", graph=STARTER_NODE_GRAPH)
            )
            first_bot = await BotStore(session).create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=config,
                graph=template.graph,
            )
            first_run = await RunStore(session).create_from_bot(first_bot)

            await template_store.update(
                template.id,
                GraphTemplateUpdate(graph=updated_graph),
            )
            revision_two = await BotStore(session).append_revision(
                first_bot.id,
                updated_graph,
            )
            assert revision_two is not None
            revised_bot = await BotStore(session).read(first_bot.id)
            assert revised_bot is not None
            second_run = await RunStore(session).create_from_bot(revised_bot)
            third_run = await RunStore(session).create_from_bot(revised_bot)

            current_template = await template_store.read(template.id)
            original_revision = await BotStore(session).read_revision(
                first_bot.id,
                first_bot.latest_graph_revision.id,
            )
            assert current_template is not None
            assert current_template.graph == updated_graph
            assert original_revision is not None
            assert original_revision.graph == STARTER_NODE_GRAPH
            assert first_run.graph == STARTER_NODE_GRAPH
            assert second_run.graph == updated_graph
            assert second_run.bot_graph_revision_id == third_run.bot_graph_revision_id

            second_bot = await BotStore(session).create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=config.model_copy(update={"name": "other"}),
                graph=current_template.graph,
            )
            assert second_bot.latest_graph_revision is not None
            assert (
                second_bot.latest_graph_revision.id
                != revised_bot.latest_graph_revision.id
            )
            session.add(
                RunRow(
                    bot_id=second_bot.id,
                    definition_id=second_bot.definition_id,
                    config=second_bot.config.model_dump(mode="json"),
                    bot_graph_revision_id=revised_bot.latest_graph_revision.id,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_persistence_updates_preserve_owned_graph_snapshots() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    async def scenario() -> None:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        graph_config = CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {"name": "before-update", "market_slugs": ["example-market"]}
        )
        async with session_factory() as session:
            template_store = GraphTemplateStore(session)
            template = await template_store.create(
                GraphTemplateCreate(name="Before rename", graph=STARTER_NODE_GRAPH)
            )
            renamed = await template_store.update(
                template.id,
                GraphTemplateUpdate(name="After rename"),
            )
            assert renamed is not None
            assert renamed.name == "After rename"
            assert renamed.graph == STARTER_NODE_GRAPH
            assert renamed.updated_at >= template.updated_at

            bot_store = BotStore(session)
            graph_bot = await bot_store.create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=graph_config,
                graph=STARTER_NODE_GRAPH,
            )
            original_revision = graph_bot.latest_graph_revision
            assert original_revision is not None
            updated_bot = await bot_store.update_config(
                graph_bot.id,
                graph_config.model_copy(update={"name": "after-update"}),
            )
            assert updated_bot is not None
            assert updated_bot.config.name == "after-update"
            assert updated_bot.latest_graph_revision == original_revision
            assert updated_bot.updated_at >= graph_bot.updated_at

            graph_run = await RunStore(session).create_from_bot(updated_bot)
            claimed = await RunStore(session).claim(
                graph_run.id,
                now=datetime.now(UTC),
            )
            assert claimed is not None
            assert claimed.status is RunStatus.STARTING
            assert claimed.bot_graph_revision_id == original_revision.id
            assert claimed.graph_revision == original_revision.revision
            assert claimed.graph == original_revision.graph

            ordinary_config = CATALOG[WINNER_DEFINITION_ID].parse_config(
                {"name": "ordinary", "max_order_size": "2"}
            )
            ordinary_bot = await bot_store.create(
                definition_id=WINNER_DEFINITION_ID,
                config=ordinary_config,
                graph=None,
            )
            restored_ordinary = await bot_store.read(ordinary_bot.id)
            listed_bots = await bot_store.list()
            ordinary_run = await RunStore(session).create_from_bot(ordinary_bot)

            assert restored_ordinary is not None
            assert restored_ordinary.latest_graph_revision is None
            assert ordinary_bot.id in {bot.id for bot in listed_bots}
            assert ordinary_run.bot_graph_revision_id is None
            assert ordinary_run.graph_revision is None
            assert ordinary_run.graph is None
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_launch_endpoint_waits_for_committed_bot_snapshot() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    original_config = CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
        {"name": "before-lock", "market_slugs": ["example-market"]}
    )
    edited_config = original_config.model_copy(update={"name": "after-lock"})
    edited_graph = NodeGraph.model_validate(threshold_buy_graph())

    async def scenario() -> None:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as setup_session:
            bot = await BotStore(setup_session).create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=original_config,
                graph=STARTER_NODE_GRAPH,
            )

        class FakeRedis:
            async def publish(self, channel: str, message: str) -> int:
                return 1

        class CapturingLauncher:
            def __init__(self) -> None:
                self.called = asyncio.Event()
                self.run: RunRead | None = None

            async def launch(self, run_id) -> None:
                async with session_factory() as launch_session:
                    self.run = await RunStore(launch_session).read(run_id)
                self.called.set()

        launcher = CapturingLauncher()
        application = create_app(
            session_factory=session_factory,
            redis=FakeRedis(),
            launcher=launcher,
        )

        async with session_factory() as edit_session:
            locked_row = (
                await edit_session.execute(
                    select(BotRow).where(BotRow.id == bot.id).with_for_update()
                )
            ).scalar_one()
            async with AsyncClient(
                transport=ASGITransport(app=application),
                base_url="http://test",
            ) as client:
                launch_task = asyncio.create_task(
                    client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot.id))
                )
                await asyncio.sleep(0)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(launcher.called.wait(), timeout=0.05)

                locked_row.config = edited_config.model_dump(mode="json")
                revision_two = BotGraphRevisionRow(
                    bot_id=bot.id,
                    revision=FIRST_GRAPH_REVISION_NUMBER + 1,
                    graph=edited_graph.model_dump(mode="json"),
                )
                edit_session.add(locked_row)
                edit_session.add(revision_two)
                await edit_session.commit()

                response = await asyncio.wait_for(launch_task, timeout=2)

        assert response.status_code == 202
        launched = RunRead.model_validate(response.json())
        assert launcher.called.is_set()
        assert launcher.run == launched
        assert launched.config == edited_config
        assert launched.bot_graph_revision_id == revision_two.id
        assert launched.graph_revision == FIRST_GRAPH_REVISION_NUMBER + 1
        assert launched.graph == edited_graph
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_concurrent_graph_revisions_receive_unique_sequence_numbers() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    async def scenario() -> None:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            bot = await BotStore(session).create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
                    {"name": "revision-race", "market_slugs": ["example-market"]}
                ),
                graph=STARTER_NODE_GRAPH,
            )

        start = asyncio.Event()

        async def append(graph: NodeGraph) -> BotRead | None:
            await start.wait()
            async with session_factory() as session:
                return await BotStore(session).append_revision(bot.id, graph)

        first_task = asyncio.create_task(
            append(NodeGraph.model_validate(threshold_buy_graph()))
        )
        second_task = asyncio.create_task(append(STARTER_NODE_GRAPH))
        start.set()
        appended = await asyncio.gather(first_task, second_task)

        assert all(result is not None for result in appended)
        revision_numbers = sorted(
            result.latest_graph_revision.revision
            for result in appended
            if result is not None and result.latest_graph_revision is not None
        )
        assert revision_numbers == [
            FIRST_GRAPH_REVISION_NUMBER + 1,
            FIRST_GRAPH_REVISION_NUMBER + 2,
        ]

        async with session_factory() as session:
            persisted = (
                await session.execute(
                    select(BotGraphRevisionRow)
                    .where(BotGraphRevisionRow.bot_id == bot.id)
                    .order_by(BotGraphRevisionRow.revision)
                )
            ).scalars()
            assert [row.revision for row in persisted] == [
                FIRST_GRAPH_REVISION_NUMBER,
                FIRST_GRAPH_REVISION_NUMBER + 1,
                FIRST_GRAPH_REVISION_NUMBER + 2,
            ]
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_persisted_node_graph_worker_writes_paper_order_and_fill_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    submitted_orders = []

    class FakeRedis:
        @classmethod
        def from_url(cls, configured_url: str) -> "FakeRedis":
            return cls()

        async def publish(self, channel: str, message: str) -> int:
            return 1

        async def aclose(self) -> None:
            return None

    class RejectingBroker:
        async def submit(self, order) -> FillEvent:
            submitted_orders.append(order)
            return FillEvent.rejected(
                order_id="paper-rejection",
                token_id=order.token_id,
                side=order.side,
                requested_size=order.size,
                received_at_ms=1_001,
                reject_reason=FillRejectReason.BOOK_UNAVAILABLE,
                reject_message="book unavailable",
            )

        async def cancel_all(self) -> None:
            return None

    class FixedClock:
        def now_ms(self) -> int:
            return 1_000

        async def sleep(self, seconds: float) -> None:
            return None

    async def run_bot(bot, runtime_config, *, observer) -> None:
        await observer.start(runtime_config)
        try:
            context = BotContext(
                config=runtime_config,
                broker=ObservableBroker(RejectingBroker(), observer, lambda: None),
                markets=AsyncMock(),
                books=AsyncMock(),
                wallet_activity=AsyncMock(),
                clock=FixedClock(),
            )
            await bot.on_book(
                context,
                BookSnapshot(
                    token_id="token",
                    bids=(BookLevel(Decimal("0.49"), Decimal(10)),),
                    asks=(BookLevel(Decimal("0.50"), Decimal(10)),),
                    received_at_ms=1_000,
                    market_slug="example-market",
                    condition_id="condition",
                ),
            )
        finally:
            await observer.stop()

    monkeypatch.setenv(DATABASE_URL_ENV, url)
    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:6379/0")
    monkeypatch.setattr(worker_resources, "Redis", FakeRedis)
    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)

    async def scenario() -> tuple[RunRead, tuple[object, ...]]:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            created = await _create_run(session,
                definition_id=NODE_BASED_DEFINITION_ID,
                config=CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
                    {
                        "name": "persisted-node",
                        "market_slugs": ["example-market"],
                    }
                ),
                graph=NodeGraph.model_validate(threshold_buy_graph()),
            )
        await execute_run(created.id)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            restored = await RunStore(session).read(created.id)
            events = await EventStore(session).read(created.id)
        assert restored is not None
        await engine.dispose()
        return restored, events

    try:
        restored, events = asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")

    assert restored.graph == NodeGraph.model_validate(threshold_buy_graph())
    assert restored.status is RunStatus.STOPPED
    assert len(submitted_orders) == 1
    assert [
        type(event)
        for event in events
        if isinstance(event, (BrokerOrderEvent, BrokerFillEvent))
    ] == [
        BrokerOrderEvent,
        BrokerFillEvent,
    ]
    assert events[-1].payload.status is RunStatus.STOPPED


@pytest.mark.postgres
@pytest.mark.parametrize("corruption", ("missing", "malformed"))
def test_worker_lifecycle_fails_closed_on_corrupt_node_graph_revision(
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    bot_starts = 0

    class FakeRedis:
        @classmethod
        def from_url(cls, configured_url: str) -> "FakeRedis":
            return cls()

        async def publish(self, channel: str, message: str) -> int:
            return 1

        async def aclose(self) -> None:
            return None

    async def run_bot(*args, **kwargs) -> None:
        nonlocal bot_starts
        bot_starts += 1

    monkeypatch.setenv(DATABASE_URL_ENV, url)
    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:6379/0")
    monkeypatch.setattr(worker_resources, "Redis", FakeRedis)
    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)

    async def scenario() -> tuple[RunRow | None, tuple[object, ...]]:
        engine = create_async_engine(url)
        config = CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {"name": f"{corruption}-graph", "market_slugs": ["example-market"]}
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            bot = await BotStore(session).create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=config,
                graph=STARTER_NODE_GRAPH,
            )
            if corruption == "missing":
                run_row = RunRow(
                    bot_id=bot.id,
                    definition_id=bot.definition_id,
                    config=config.model_dump(mode="json"),
                    bot_graph_revision_id=None,
                )
                session.add(run_row)
                await session.commit()
                await session.refresh(run_row)
                run_id = run_row.id
            else:
                created = await RunStore(session).create_from_bot(bot)
                assert bot.latest_graph_revision is not None
                revision_row = await session.get(
                    BotGraphRevisionRow,
                    bot.latest_graph_revision.id,
                )
                assert revision_row is not None
                revision_row.graph = {"nodes": [], "edges": []}
                session.add(revision_row)
                await session.commit()
                run_id = created.id

        await execute_run(run_id)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            restored = await session.get(RunRow, run_id)
            events = await EventStore(session).read(run_id)
        await engine.dispose()
        return restored, events

    try:
        restored, events = asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")

    assert bot_starts == 0
    assert restored is not None
    assert restored.status is RunStatus.FAILED
    assert restored.failure_detail == worker_lifecycle.PAPER_RUN_FAILURE_REASON
    assert events[-1].payload.status is RunStatus.FAILED


@pytest.mark.postgres
def test_graph_template_api_rolls_back_name_conflicts() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    async def scenario() -> None:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        class FakeRedis:
            async def publish(self, channel: str, message: str) -> int:
                return 1

        application = create_app(
            session_factory=session_factory,
            redis=FakeRedis(),
            launcher=AsyncMock(),
        )
        graph = STARTER_NODE_GRAPH.model_dump(mode="json")
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            first = await client.post(
                api_route_path(GRAPH_TEMPLATES_PATH),
                json={"name": "Existing", "graph": graph},
            )
            duplicate = await client.post(
                api_route_path(GRAPH_TEMPLATES_PATH),
                json={"name": "Existing", "graph": graph},
            )
            second = await client.post(
                api_route_path(GRAPH_TEMPLATES_PATH),
                json={"name": "Second", "graph": graph},
            )
            conflicting_rename = await client.patch(
                api_route_path(
                    GRAPH_TEMPLATE_PATH,
                    template_id=second.json()["id"],
                ),
                json={"name": "Existing"},
            )
            recovered_rename = await client.patch(
                api_route_path(
                    GRAPH_TEMPLATE_PATH,
                    template_id=second.json()["id"],
                ),
                json={"name": "Recovered"},
            )
            listed = await client.get(api_route_path(GRAPH_TEMPLATES_PATH))

        assert first.status_code == 201
        assert duplicate.status_code == 409
        assert second.status_code == 201
        assert conflicting_rename.status_code == 409
        assert recovered_rename.status_code == 200
        assert [template["name"] for template in listed.json()] == [
            "Existing",
            "Recovered",
        ]
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_expired_worker_lease_interrupts_once_and_never_relaunches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    config = CATALOG[WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID].parse_config(
        {
            "name": "expired-worker",
            "wallet_addresses": [
                "0x0000000000000000000000000000000000000001"
            ],
        }
    )

    async def scenario() -> None:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        class FakeRedis:
            async def publish(self, channel: str, message: str) -> int:
                return 1

        now = datetime.now(UTC)
        lease_started_at = now - timedelta(seconds=30)
        async with session_factory() as session:
            run = await _create_run(
                session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config,
            )
            store = RunStore(session)
            assert await store.claim(run.id, now=lease_started_at) is not None
            assert await store.mark_running(run.id)

        writer = RunEventWriter(session_factory, FakeRedis())
        reconciliations = await asyncio.gather(
            *(
                reconcile_expired_run(
                    run.id,
                    expired_before=now - timedelta(seconds=5),
                    now=now,
                    session_factory=session_factory,
                    event_writer=writer,
                )
                for _ in range(2)
            )
        )

        bot_starts = 0

        async def run_claimed_bot(run, observer) -> None:
            nonlocal bot_starts
            bot_starts += 1

        monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
        async with session_factory() as session:
            await worker_lifecycle.RunLifecycleCoordinator(
                RunStore(session),
                session_factory,
                writer,
            ).execute(run.id)
        async with session_factory() as session:
            restored = await RunStore(session).read(run.id)
            events = await EventStore(session).read(run.id)

        assert reconciliations.count(True) == 1
        assert restored is not None
        assert restored.status is RunStatus.INTERRUPTED
        assert [event.payload.status for event in events] == [
            RunStatus.INTERRUPTED
        ]
        assert bot_starts == 0
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_concurrent_claim_stop_lease_and_event_ordering() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    config = CATALOG[WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID].parse_config(
        {
            "name": "concurrent",
            "wallet_addresses": [
                "0x0000000000000000000000000000000000000001"
            ],
        }
    )

    async def scenario() -> None:
        engine = create_async_engine(url)

        def session_factory() -> AsyncSession:
            return AsyncSession(engine, expire_on_commit=False)

        async with session_factory() as session:
            queued = await _create_run(session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config,
            )
            queued_stop = await _create_run(session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "queued-stop"}),
            )
            starting_stop = await _create_run(session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "starting-stop"}),
            )
            failed_run = await _create_run(session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "failed"}),
            )
            interrupted_run = await _create_run(session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "interrupted"}),
            )
            malformed_run = RunRow(
                bot_id=queued.bot_id,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config={},
            )
            session.add(malformed_run)
            await session.commit()
            await session.refresh(malformed_run)

        async def claim() -> RunRead | None:
            async with session_factory() as session:
                return await RunStore(session).claim(
                    queued.id,
                    now=datetime.now(UTC),
                )

        claims = await asyncio.gather(claim(), claim())
        assert sum(claim is not None for claim in claims) == 1
        assert {claim.status for claim in claims if claim is not None} == {
            RunStatus.STARTING
        }

        now = datetime.now(UTC)
        async with session_factory() as session:
            store = RunStore(session)
            assert (
                await store.request_stop(queued_stop.id, now=now)
                is RunStatus.STOPPED
            )
            assert (
                await store.request_stop(queued_stop.id, now=now)
                is RunStatus.STOPPED
            )
            assert await store.claim(starting_stop.id, now=now) is not None
            assert (
                await store.request_stop(starting_stop.id, now=now)
                is RunStatus.STOP_REQUESTED
            )
            assert (
                await store.request_stop(starting_stop.id, now=now)
                is RunStatus.STOP_REQUESTED
            )
            assert await store.begin_stopping(starting_stop.id)
            assert (
                await store.request_stop(starting_stop.id, now=now)
                is RunStatus.STOPPING
            )
            assert await store.finish(
                starting_stop.id,
                status=RunStatus.STOPPED,
                now=now,
            )
            assert await store.interrupt_expired(
                queued.id,
                expired_before=now + timedelta(seconds=1),
                now=now,
            )
            assert not await store.interrupt_expired(
                queued.id,
                expired_before=now + timedelta(seconds=1),
                now=now,
            )
            assert await store.claim(queued.id, now=now) is None
            assert await store.request_stop(uuid4(), now=now) is None
            assert await store.claim(failed_run.id, now=now) is not None
            assert await store.mark_running(failed_run.id)
            assert await store.finish(
                failed_run.id,
                status=RunStatus.FAILED,
                now=now,
                failure_detail="sanitized failure",
            )
            assert await store.claim(interrupted_run.id, now=now) is not None
            assert await store.finish(
                interrupted_run.id,
                status=RunStatus.INTERRUPTED,
                now=now,
            )

        async with session_factory() as session:
            with pytest.raises(ValidationError):
                await RunStore(session).claim(malformed_run.id, now=now)
        async with session_factory() as session:
            malformed_row = await session.get(RunRow, malformed_run.id)
            failed = await RunStore(session).read(failed_run.id)
            interrupted = await RunStore(session).read(interrupted_run.id)

        assert malformed_row is not None
        assert malformed_row.status is RunStatus.QUEUED
        assert failed is not None
        assert failed.status is RunStatus.FAILED
        assert failed.ended_at == now
        assert failed.heartbeat_at is not None
        assert failed.failure_detail == "sanitized failure"
        assert interrupted is not None
        assert interrupted.status is RunStatus.INTERRUPTED
        assert interrupted.ended_at == now
        assert interrupted.heartbeat_at is not None
        assert interrupted.failure_detail is None

        other_run_id = queued_stop.id
        first = RunLifecycleEvent(
            run_id=queued.id,
            occurred_at=now,
            payload=RunStatusPayload(status=RunStatus.STARTING),
        )
        other = RunLifecycleEvent(
            run_id=other_run_id,
            occurred_at=now,
            payload=RunStatusPayload(status=RunStatus.STOPPED),
        )
        last = RunLifecycleEvent(
            run_id=queued.id,
            occurred_at=now,
            payload=RunStatusPayload(status=RunStatus.INTERRUPTED),
        )
        async with session_factory() as session:
            event_store = EventStore(session)
            stored_first = await event_store.append(first)
            await event_store.append(other)
            stored_last = await event_store.append(last)
            restored = await event_store.read(queued.id)
            after_first = await event_store.read(
                queued.id,
                after_event_id=stored_first.id,
            )
            bounded = await event_store.read(queued.id, limit=1)
            newest_page = await event_store.read_page(
                queued.id,
                before_event_id=None,
                limit=1,
            )
            older_page = await event_store.read_page(
                queued.id,
                before_event_id=newest_page.next_before_event_id,
                limit=1,
            )
            for run_id, equity in (
                (queued.id, "101"),
                (other_run_id, "201"),
                (queued.id, "102"),
            ):
                await event_store.append(
                    ChartSampleEvent(
                        run_id=run_id,
                        occurred_at=now,
                        payload=ChartSamplePayload(
                            sampled_at_ms=int(equity),
                            markets=(),
                            equity=EquityChartPointPayload(
                                value=equity,
                                status=ValuationStatus.FRESH,
                            ),
                        ),
                    )
                )
            latest_samples = await event_store.latest_chart_samples(
                (queued.id, other_run_id)
            )

        assert [event.id for event in restored] == [
            stored_first.id,
            stored_last.id,
        ]
        assert after_first == (stored_last,)
        assert bounded == (stored_first,)
        assert newest_page.events == (stored_last,)
        assert newest_page.next_before_event_id == stored_last.id
        assert older_page.events == (stored_first,)
        assert older_page.next_before_event_id is None
        assert latest_samples[queued.id].payload.equity.value == Decimal("102")
        assert latest_samples[other_run_id].payload.equity.value == Decimal("201")
        assert all(event.kind is EventKind.RUN_LIFECYCLE for event in restored)
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")


@pytest.mark.postgres
def test_duplicate_worker_delivery_starts_one_bot_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    bot_starts = 0

    class FakeRedis:
        @classmethod
        def from_url(cls, configured_url: str) -> "FakeRedis":
            return cls()

        async def publish(self, channel: str, message: str) -> int:
            return 1

        async def aclose(self) -> None:
            return None

    async def run_claimed_bot(run: RunRead, observer: object) -> None:
        nonlocal bot_starts
        bot_starts += 1

    monkeypatch.setenv(DATABASE_URL_ENV, url)
    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:6379/0")
    monkeypatch.setattr(worker_resources, "Redis", FakeRedis)
    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)

    async def scenario() -> tuple[RunRead | None, tuple[RunLifecycleEvent, ...]]:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            created = await _create_run(session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=CATALOG[
                    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID
                ].parse_config(
                    {
                        "name": "duplicate-worker",
                        "wallet_addresses": [
                            "0x0000000000000000000000000000000000000001"
                        ],
                    }
                ),
            )
        await asyncio.gather(execute_run(created.id), execute_run(created.id))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            restored = await RunStore(session).read(created.id)
            events = await EventStore(session).read(created.id)
        await engine.dispose()
        return restored, events

    try:
        restored, events = asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")

    assert bot_starts == 1
    assert restored is not None
    assert restored.status is RunStatus.STOPPED
    assert events[-1].payload.status is RunStatus.STOPPED
