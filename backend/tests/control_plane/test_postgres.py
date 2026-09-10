from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import api.execution.worker.lifecycle as worker_lifecycle
import api.execution.worker.resources as worker_resources
import api.execution.worker.runtime as worker_runtime
import pytest
from alembic import command
from alembic.config import Config
from api.auth.models import UserRow
from api.bots.models import BotRow
from api.bots.schema import (
    BOTS_TABLE_NAME,
)
from api.bots.store import BotStore
from api.catalog.definitions import (
    CATALOG,
    NODE_BASED_DEFINITION_ID,
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
    WINNER_DEFINITION_ID,
    GraphRequirementError,
)
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.examples import entry_exit_example
from api.catalog.graphs.starter import STARTER_NODE_GRAPH
from api.database import DATABASE_URL_ENV, async_database_url
from api.events.contracts import (
    BrokerFillEvent,
    BrokerOrderEvent,
    ChartSampleEvent,
    ChartSamplePayload,
    PersistedBrokerFillEvent,
    PersistedBrokerOrderEvent,
    RunFailureEvent,
    RunFailurePayload,
    RunLifecycleEvent,
    RunStatusPayload,
)
from api.events.contracts.payloads.chart import EquityChartPointPayload
from api.events.kinds import EventKind
from api.events.models import EventRow
from api.events.schema import (
    EVENT_KIND_CONSTRAINT_NAME,
    RUN_EVENTS_CURSOR_INDEX_NAME,
    RUN_EVENTS_TABLE_NAME,
    EventColumn,
)
from api.events.store import EventStore
from api.events.writer import RunEventWriter
from api.execution.config import REDIS_URL_ENV
from api.execution.worker import execute_run
from api.http.routes.paths import (
    BOT_RUNS_PATH,
    api_route_path,
)
from api.runs.contracts import RunRead
from api.runs.failures import INTERRUPTION_DETAIL
from api.runs.models import RunRow
from api.runs.schema import (
    INTERNAL_RUN_COLUMNS,
    RUN_STATUS_CONSTRAINT_NAME,
    RUNS_TABLE_NAME,
    RunColumn,
)
from api.runs.status import RunStatus
from api.runs.store import RunStore
from httpx import ASGITransport, AsyncClient
from polybot.cli.observability.broker import ObservableBroker
from polybot.framework.context import BotContext
from polybot.framework.events import FillEvent, FillRejectReason
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.streams import StreamRelation
from polybot.performance.contracts.valuation_status import ValuationStatus
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

from control_plane.auth_fixtures import TEST_HEADERS, ensure_test_user
from control_plane.auth_fixtures import create_authenticated_app as create_app
from control_plane.graph_fixtures import threshold_buy_graph
from control_plane.service_config import (
    POSTGRES_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
)

BACKEND_ROOT = Path(__file__).parents[2]


def _postgres_url() -> str:
    url = os.getenv(TEST_POSTGRES_URL_ENV)
    if url is None:
        pytest.skip(POSTGRES_NOT_CONFIGURED_SKIP_REASON)
    return async_database_url(url).render_as_string(hide_password=False)


def _alembic_config(url: str) -> Config:
    config = Config(BACKEND_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


def _run_insert_statement() -> TextClause:
    columns = ", ".join(
        column.value for column in RunColumn if column not in INTERNAL_RUN_COLUMNS
    )
    values = ", ".join(
        (
            f"CAST(:{column.value} AS JSONB)"
            if column is RunColumn.CONFIG_SNAPSHOT
            else f":{column.value}"
        )
        for column in RunColumn
        if column not in INTERNAL_RUN_COLUMNS
    )
    return text(f"INSERT INTO {RUNS_TABLE_NAME} ({columns}) VALUES ({values})")


async def _create_run(
    session: AsyncSession,
    *,
    definition_id: str,
    config,
    graph: NodeGraph | None = None,
    owner_user_id: UUID | None = None,
) -> RunRead:
    bot = await BotStore(
        session, owner_user_id or await ensure_test_user(session)
    ).create(
        definition_id=definition_id,
        config=config.model_copy(update={"graph": graph}, deep=True),
    )
    return await RunStore(session).create_from_bot(bot)


@pytest.mark.postgres
def test_initial_migration_upgrade_and_downgrade_schema_and_cursor_index() -> None:
    url = _postgres_url()
    config = _alembic_config(url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

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
                lambda sync_connection: inspect(sync_connection).get_check_constraints(
                    RUNS_TABLE_NAME
                )
            )
            primary_key = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_pk_constraint(
                    RUNS_TABLE_NAME
                )
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
                    lambda sync_connection: inspect(sync_connection).get_foreign_keys(
                        RUN_EVENTS_TABLE_NAME
                    )
                )
                event_primary_key = await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_pk_constraint(
                        RUN_EVENTS_TABLE_NAME
                    )
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
        BOTS_TABLE_NAME,
    }.issubset(table_names)
    assert set(column["name"] for column in columns) == set(
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
    assert {index["name"] for index in event_indexes} == {RUN_EVENTS_CURSOR_INDEX_NAME}
    assert event_indexes[0]["column_names"] == [
        EventRow.run_id.name,
        EventRow.id.name,
    ]
    assert {check["name"] for check in event_checks} == {EVENT_KIND_CONSTRAINT_NAME}
    assert EventKind.CHART_SAMPLE.value in event_checks[0]["sqltext"]
    assert len(event_foreign_keys) == 1
    assert event_foreign_keys[0]["constrained_columns"] == [EventRow.run_id.name]
    assert event_foreign_keys[0]["referred_table"] == RUNS_TABLE_NAME
    assert event_foreign_keys[0]["referred_columns"] == [RunRow.id.name]

    async def assert_constraint_rejections() -> None:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            bot = await BotStore(session, await ensure_test_user(session)).create(
                definition_id=WINNER_DEFINITION_ID,
                config=CATALOG[WINNER_DEFINITION_ID]
                .parse_config({"name": "constraint"})
                .model_copy(update={"graph": None}, deep=True),
            )
        statement = _run_insert_statement()
        common_values = {
            RunColumn.BOT_ID.value: bot.id,
            RunColumn.DEFINITION_ID.value: "definition",
            RunColumn.CONFIG_SNAPSHOT.value: json.dumps({}),
            RunColumn.STATUS.value: RunStatus.QUEUED.value,
            RunColumn.CREATED_AT.value: datetime.now(UTC),
            RunColumn.STARTED_AT.value: None,
            RunColumn.ENDED_AT.value: None,
            RunColumn.HEARTBEAT_AT.value: None,
            RunColumn.FAILURE_DETAIL.value: None,
        }
        invalid_rows = (
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

    async def insert_chart_sample() -> None:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            bot_id = await session.scalar(select(BotRow.id).limit(1))
            assert bot_id is not None
        run_id = uuid4()
        run_values = {
            RunColumn.ID.value: run_id,
            RunColumn.BOT_ID.value: bot_id,
            RunColumn.DEFINITION_ID.value: "definition",
            RunColumn.CONFIG_SNAPSHOT.value: json.dumps({}),
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
        await engine.dispose()

    asyncio.run(insert_chart_sample())

    command.downgrade(config, "base")

    async def remaining_tables() -> list[str]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync: inspect(sync).get_table_names()
                )
        finally:
            await engine.dispose()

    assert asyncio.run(remaining_tables()) == ["alembic_version"]
    command.upgrade(config, "head")
    assert set(asyncio.run(inspect_schema())[0]) == set(table_names)


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
            first = await _create_run(
                session,
                definition_id=definition_id,
                config=config,
                graph=expected_graph,
            )
            second = await _create_run(
                session,
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
                    config_snapshot=config.model_dump(mode="json"),
                    created_at=tied_at,
                ),
                RunRow(
                    id=uuid4(),
                    bot_id=first.bot_id,
                    definition_id=definition_id,
                    config_snapshot=config.model_dump(mode="json"),
                    created_at=tied_at,
                ),
            )
            session.add_all(tied_rows)
            await session.commit()
            runs = await store.list()
        await engine.dispose()
        return first, second, restored, missing, runs, tied_rows

    try:
        first, second, restored, missing, runs, tied_rows = asyncio.run(round_trip())
    finally:
        command.downgrade(alembic_config, "base")

    assert isinstance(restored, RunRead)
    assert restored.status is RunStatus.QUEUED
    assert restored.config.model_dump(mode="json") == config.model_copy(
        update={"graph": expected_graph}
    ).model_dump(mode="json")
    assert restored.config.max_order_size.as_tuple() == config.max_order_size.as_tuple()
    assert restored.config.stream_rules[0].relation is StreamRelation.INDEPENDENT
    assert restored.config.stream_rules[0].market_slugs == ("example-market",)
    assert restored.config.graph == expected_graph
    assert missing is None
    run_ids = tuple(run.id for run in runs)
    assert tuple(run_id for run_id in run_ids if run_id in {first.id, second.id}) == (
        second.id,
        first.id,
    )
    assert tuple(
        run_id for run_id in run_ids if run_id in {row.id for row in tied_rows}
    ) == tuple(sorted((row.id for row in tied_rows), reverse=True))


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
    edited_config = edited_config.model_copy(update={"graph": edited_graph}, deep=True)

    async def scenario() -> None:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as setup_session:
            bot = await BotStore(
                setup_session, await ensure_test_user(setup_session)
            ).create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=original_config.model_copy(
                    update={"graph": STARTER_NODE_GRAPH}, deep=True
                ),
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
        async with session_factory() as identity_session:
            await ensure_test_user(identity_session)
            await identity_session.commit()
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
                headers=TEST_HEADERS,
            ) as client:
                launch_task = asyncio.create_task(
                    client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot.id))
                )
                await asyncio.sleep(0)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(launcher.called.wait(), timeout=0.05)

                locked_row.config = edited_config.model_dump(mode="json")
                edit_session.add(locked_row)
                await edit_session.commit()

                response = await asyncio.wait_for(launch_task, timeout=2)

        assert response.status_code == 202
        launched = RunRead.model_validate(response.json())
        assert launcher.called.is_set()
        assert launcher.run == launched
        assert launched.config == edited_config
        assert launched.config.graph == edited_graph
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
        def from_url(cls, configured_url: str, **kwargs) -> "FakeRedis":
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

    async def run_bot(
        bot, runtime_config, *, observer, max_tracked_markets, execution_scope
    ) -> None:
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
            created = await _create_run(
                session,
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

    assert restored.config.graph == NodeGraph.model_validate(threshold_buy_graph())
    assert restored.status is RunStatus.STOPPED
    assert len(submitted_orders) == 1
    assert [
        type(event)
        for event in events
        if isinstance(event, (BrokerOrderEvent, BrokerFillEvent))
    ] == [
        PersistedBrokerOrderEvent,
        PersistedBrokerFillEvent,
    ]
    assert events[-1].payload.status is RunStatus.STOPPED


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("corruption", "error_type"),
    (("missing", GraphRequirementError), ("malformed", ValidationError)),
)
def test_worker_lifecycle_fails_closed_on_corrupt_node_graph_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    error_type: type[Exception],
) -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    bot_starts = 0

    class FakeRedis:
        @classmethod
        def from_url(cls, configured_url: str, **kwargs) -> "FakeRedis":
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
            bot = await BotStore(session, await ensure_test_user(session)).create(
                definition_id=NODE_BASED_DEFINITION_ID,
                config=config.model_copy(
                    update={"graph": STARTER_NODE_GRAPH}, deep=True
                ),
            )
            if corruption == "missing":
                run_row = RunRow(
                    bot_id=bot.id,
                    definition_id=bot.definition_id,
                    config_snapshot=config.model_dump(mode="json"),
                )
                session.add(run_row)
                await session.commit()
                await session.refresh(run_row)
                run_id = run_row.id
            else:
                created = await RunStore(session).create_from_bot(bot)
                run_row = await session.get(RunRow, created.id)
                run_row.config_snapshot = {
                    **run_row.config_snapshot,
                    "graph": {"nodes": [], "edges": []},
                }
                session.add(run_row)
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
    assert restored.failure_detail == (
        f"{error_type.__name__}: {worker_lifecycle.PAPER_RUN_FAILURE_REASON}"
    )
    assert events[-1].payload.status is RunStatus.FAILED


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
            "wallet_addresses": ["0x0000000000000000000000000000000000000001"],
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

        async def reconcile_once():
            async with session_factory() as session:
                return await RunStore(session).interrupt_expired(
                    run.id, now=now, expired_before=now - timedelta(seconds=5)
                )

        reconciliations = await asyncio.gather(reconcile_once(), reconcile_once())

        bot_starts = 0

        async def run_claimed_bot(run, observer, **kwargs) -> None:
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
        assert [event.payload.status for event in events] == [RunStatus.INTERRUPTED]
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
            "wallet_addresses": ["0x0000000000000000000000000000000000000001"],
        }
    )

    async def scenario() -> None:
        engine = create_async_engine(url)

        def session_factory() -> AsyncSession:
            return AsyncSession(engine, expire_on_commit=False)

        async with session_factory() as session:
            owners = [
                UserRow(email=f"{uuid4()}@example.com", password_hash="fixture")
                for _ in range(5)
            ]
            session.add_all(owners)
            await session.commit()
            queued = await _create_run(
                session,
                owner_user_id=owners[0].id,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config,
            )
            queued_stop = await _create_run(
                session,
                owner_user_id=owners[1].id,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "queued-stop"}),
            )
            starting_stop = await _create_run(
                session,
                owner_user_id=owners[2].id,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "starting-stop"}),
            )
            failed_run = await _create_run(
                session,
                owner_user_id=owners[3].id,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "failed"}),
            )
            interrupted_run = await _create_run(
                session,
                owner_user_id=owners[4].id,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=config.model_copy(update={"name": "interrupted"}),
            )
            malformed_run = RunRow(
                bot_id=queued.bot_id,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config_snapshot={},
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
                await store.request_stop(queued_stop.id, now=now) is RunStatus.STOPPED
            )
            assert (
                await store.request_stop(queued_stop.id, now=now) is RunStatus.STOPPED
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
        assert interrupted.failure_detail == INTERRUPTION_DETAIL

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
            terminal_history = await event_store.read(queued.id)
            assert len(terminal_history) == 1
            assert terminal_history[0].payload.status is RunStatus.INTERRUPTED
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
            for run_id, error in (
                (queued.id, "ValueError: first failure"),
                (other_run_id, "RuntimeError: other failure"),
                (queued.id, "ConnectionError: latest failure"),
            ):
                await event_store.append(
                    RunFailureEvent(
                        run_id=run_id,
                        occurred_at=now,
                        payload=RunFailurePayload(error=error),
                    )
                )
            latest_failures = await event_store.latest_run_failures(
                (queued.id, other_run_id)
            )

        assert [event.id for event in restored] == [
            terminal_history[0].id,
            stored_first.id,
            stored_last.id,
        ]
        assert after_first == (stored_last,)
        assert bounded == terminal_history
        assert newest_page.events == (stored_last,)
        assert newest_page.next_before_event_id == stored_last.id
        assert older_page.events == (stored_first,)
        assert older_page.next_before_event_id == stored_first.id
        assert latest_samples[queued.id].payload.equity.value == Decimal("102")
        assert latest_samples[other_run_id].payload.equity.value == Decimal("201")
        assert latest_failures[queued.id].payload.error == (
            "ConnectionError: latest failure"
        )
        assert latest_failures[other_run_id].payload.error == (
            "RuntimeError: other failure"
        )
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
        def from_url(cls, configured_url: str, **kwargs) -> "FakeRedis":
            return cls()

        async def publish(self, channel: str, message: str) -> int:
            return 1

        async def aclose(self) -> None:
            return None

    async def run_claimed_bot(run: RunRead, observer: object, **kwargs) -> None:
        nonlocal bot_starts
        bot_starts += 1

    monkeypatch.setenv(DATABASE_URL_ENV, url)
    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:6379/0")
    monkeypatch.setattr(worker_resources, "Redis", FakeRedis)
    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)

    async def scenario() -> tuple[RunRead | None, tuple[RunLifecycleEvent, ...]]:
        engine = create_async_engine(url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            created = await _create_run(
                session,
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                config=CATALOG[WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID].parse_config(
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


@pytest.mark.postgres
def test_graph_parameters_preserve_exact_values_and_run_snapshots() -> None:
    url = _postgres_url()
    alembic_config = _alembic_config(url)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    graph_data = entry_exit_example().graph.model_dump(mode="json")
    exact_value = "9007199254740993.000000000000000001"
    graph_data["parameters"][0]["data"]["value"] = exact_value
    graph = NodeGraph.model_validate(graph_data)
    config = CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
        {"name": "parameter isolation", "market_slugs": ["example-market"]}
    )

    async def scenario() -> None:
        engine = create_async_engine(url)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                bots = BotStore(session, await ensure_test_user(session))
                bot = await bots.create(
                    definition_id=NODE_BASED_DEFINITION_ID,
                    config=config.model_copy(update={"graph": graph}, deep=True),
                )
                run = await RunStore(session).create_from_bot(bot)
                graph_data["parameters"][0]["data"]["value"] = "0.25"
                replacement = NodeGraph.model_validate(graph_data)
                await bots.update_config(
                    bot.id,
                    bot.config.model_copy(update={"graph": replacement}, deep=True),
                )
                session.expire_all()
                latest = await bots.read(bot.id)
                saved_run = await RunStore(session).read(run.id)
                assert saved_run.config.graph.parameters[0].data.value == exact_value
                assert saved_run.config.graph == graph
                assert latest.config.graph == replacement
                copied = await bots.create(
                    definition_id=NODE_BASED_DEFINITION_ID,
                    config=config.model_copy(
                        update={"graph": saved_run.config.graph}, deep=True
                    ),
                )
                assert copied.config.graph == graph
                assert copied.id != bot.id
        finally:
            await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        command.downgrade(alembic_config, "base")
