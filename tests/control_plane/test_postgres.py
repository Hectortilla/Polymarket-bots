from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from pydantic import ValidationError

import polybot_control_plane.execution.worker.lifecycle as worker_lifecycle
import polybot_control_plane.execution.worker.resources as worker_resources
from polybot.framework.streams import StreamRelation
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    INITIAL_DEFINITION_VERSION,
    WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
)
from polybot_control_plane.database import DATABASE_URL_ENV, async_database_url
from polybot_control_plane.events.contracts import (
    ChartSampleEvent,
    ChartSamplePayload,
    EventKind,
    RunLifecycleEvent,
    RunStatusPayload,
)
from polybot_control_plane.events.contracts.payloads import EquityChartPointPayload
from polybot_control_plane.events.models import EventRow
from polybot_control_plane.events.schema import (
    EVENT_KIND_CONSTRAINT_NAME,
    EventColumn,
    RUN_EVENTS_CURSOR_INDEX_NAME,
    RUN_EVENTS_RUN_ID_INDEX_NAME,
    RUN_EVENTS_TABLE_NAME,
)
from polybot_control_plane.events.store import EventStore
from polybot_control_plane.execution.config import REDIS_URL_ENV
from polybot_control_plane.execution.worker import execute_run
from polybot_control_plane.runs.contracts import RunRead, RunStatus
from polybot_control_plane.runs.models import RunRow
from polybot_control_plane.runs.schema import (
    DEFINITION_VERSION_CONSTRAINT_NAME,
    RunColumn,
    RUNS_TABLE_NAME,
    RUN_STATUS_CONSTRAINT_NAME,
)
from polybot_control_plane.runs.store import RunStore
from polybot.performance.contracts.valuation_status import ValuationStatus
from control_plane.service_config import (
    POSTGRES_NOT_CONFIGURED_SKIP_REASON,
    TEST_POSTGRES_URL_ENV,
)


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
        if column.value in RunRead.model_fields
    )[:6]
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
        statement = _run_insert_statement()
        common_values = {
            RunColumn.DEFINITION_ID.value: "definition",
            RunColumn.DEFINITION_VERSION.value: INITIAL_DEFINITION_VERSION,
            RunColumn.CONFIG.value: json.dumps({}),
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

    async def insert_chart_sample(*, accepted: bool) -> None:
        engine = create_async_engine(url)
        run_id = uuid4()
        run_values = {
            RunColumn.ID.value: run_id,
            RunColumn.DEFINITION_ID.value: "definition",
            RunColumn.DEFINITION_VERSION.value: INITIAL_DEFINITION_VERSION,
            RunColumn.CONFIG.value: json.dumps({}),
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
                    text(
                        f"DELETE FROM {RUN_EVENTS_TABLE_NAME} "
                        f"WHERE {EventColumn.RUN_ID} = :run_id"
                    ),
                    {"run_id": run_id},
                )

        if accepted:
            await insert()
        else:
            with pytest.raises(IntegrityError):
                await insert()
        await engine.dispose()

    asyncio.run(insert_chart_sample(accepted=True))

    command.downgrade(config, "0002")
    slice_12b_schema = asyncio.run(inspect_schema())
    assert {index["name"] for index in slice_12b_schema[5]} == {
        RUN_EVENTS_RUN_ID_INDEX_NAME
    }
    assert slice_12b_schema[5][0]["column_names"] == [EventRow.run_id.name]
    assert EventKind.CHART_SAMPLE.value not in slice_12b_schema[6][0]["sqltext"]
    asyncio.run(insert_chart_sample(accepted=False))

    command.downgrade(config, "0001")
    downgraded_schema = asyncio.run(inspect_schema())
    assert RUN_EVENTS_TABLE_NAME not in downgraded_schema[0]
    assert tuple(column["name"] for column in downgraded_schema[1]) == tuple(
        column.value for column in RunColumn
    )[:6]
    command.downgrade(config, "base")


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
        session_factory = lambda: AsyncSession(engine, expire_on_commit=False)
        async with session_factory() as session:
            queued = await RunStore(session).create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
                config=config,
            )
            queued_stop = await RunStore(session).create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
                config=config.model_copy(update={"name": "queued-stop"}),
            )
            starting_stop = await RunStore(session).create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
                config=config.model_copy(update={"name": "starting-stop"}),
            )
            failed_run = await RunStore(session).create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
                config=config.model_copy(update={"name": "failed"}),
            )
            interrupted_run = await RunStore(session).create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
                config=config.model_copy(update={"name": "interrupted"}),
            )
            malformed_run = RunRow(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
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
            assert await store.request_stop(queued_stop.id, now=now) is RunStatus.STOPPED
            assert await store.request_stop(queued_stop.id, now=now) is RunStatus.STOPPED
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
            created = await RunStore(session).create(
                definition_id=WALLET_FILTER_COPY_EXAMPLE_DEFINITION_ID,
                definition_version=INITIAL_DEFINITION_VERSION,
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
