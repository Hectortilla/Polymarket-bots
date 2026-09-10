"""Operational adapters reject ambiguous Redis values and preserve unavailable feed state."""

import asyncio
import json
from datetime import timedelta
from threading import Event
from time import monotonic
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from api.events.contracts import LiveStreamHealthEvent
from api.events.health.contracts import FeedObservation
from api.events.health.policy import FEED_TTL_SECONDS
from api.events.health.store import FeedHealthStore
from api.execution.taskiq_app import broker
from api.limits.errors import ResourceLimitCode, ResourceLimitError
from api.limits.http import resource_limit_response
from api.operations.alerts import ALERT_DEFINITIONS
from api.operations.alerts.contracts import ThresholdDirection
from api.operations.http import OperationalHttpMiddleware
from api.operations.measurement_contracts import DatabaseMeasurements
from api.operations.measurements import OperationMeasurements
from api.operations.monitor import OperationMonitor
from api.operations.monitor.probes import StorageProbe
from api.operations.observations.contracts import (
    AlertCode,
    FailureObservation,
    Observation,
)
from api.operations.observations.sink import (
    MAX_QUEUED_OPERATION_RECORDS,
    OPERATION_LOG,
    OperationLog,
)
from api.operations.telemetry.counters import (
    MAX_METRIC_COUNT,
    ObservationCounters,
)
from api.operations.telemetry.errors import TelemetryDataError
from api.operations.telemetry.presence import (
    WORKER_KEY_PREFIX,
    WORKER_PRESENCE_MARKER,
    WorkerPresenceStore,
)
from api.operations.telemetry.presence_policy import PRESENCE_TTL_SECONDS
from api.operations.worker import (
    WorkerPresence,
    start_worker_presence,
    stop_worker_presence,
)
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from polybot.cli.observability.events import StreamHealth
from polybot.framework.clock import system_now_utc
from taskiq import TaskiqEvents, TaskiqState

from control_plane.limits_fixtures import limits_services as limits_services
from control_plane.limits_fixtures import resource_services


@pytest.mark.parametrize(
    "definition",
    [
        entry
        for entry in ALERT_DEFINITIONS.values()
        if entry.direction is not ThresholdDirection.UNAVAILABLE
    ],
    ids=lambda entry: entry.code,
)
def test_alert_threshold_includes_boundary_but_not_neighbor(definition):
    assert definition.breached(definition.threshold)
    neighbor = (
        definition.threshold - 1
        if definition.direction is ThresholdDirection.AT_LEAST
        else definition.threshold + 1
    )
    assert not definition.breached(neighbor)


def test_counter_windows_and_malformed_values(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            counters = ObservationCounters(redis)
            with patch.object(ObservationCounters, "current_bucket", return_value=10):
                await counters.increment(Observation.HTTP_ERROR)
                await redis.set(counters.key(Observation.HTTP_ERROR, 9), 2)
                await redis.set(counters.key(Observation.HTTP_ERROR, 8), 99)
                assert await counters.recent_count(Observation.HTTP_ERROR) == 3
                for value in (-1, MAX_METRIC_COUNT + 1, "malformed"):
                    await redis.set(counters.key(Observation.HTTP_ERROR, 10), value)
                    with pytest.raises(TelemetryDataError):
                        await counters.recent_count(Observation.HTTP_ERROR)

    asyncio.run(scenario())


def test_worker_presence_requires_uuid_marker_and_expiry(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            store = WorkerPresenceStore(redis)
            worker_id = uuid4()
            await store.refresh(worker_id)
            assert await store.count() == 1
            await store.remove(worker_id)
            assert await store.count() == 0
            cases = [
                (
                    WORKER_KEY_PREFIX + "invalid",
                    WORKER_PRESENCE_MARKER,
                    PRESENCE_TTL_SECONDS,
                ),
                (store.key(worker_id), "bad", PRESENCE_TTL_SECONDS),
                (store.key(worker_id), WORKER_PRESENCE_MARKER, None),
            ]
            for key, marker, expiry in cases:
                await redis.set(key, marker, ex=expiry)
                with pytest.raises(TelemetryDataError):
                    await store.count()
                await redis.delete(key)

    asyncio.run(scenario())


def test_feed_missing_malformed_stale_and_unknown_lag_remain_unavailable(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            store = FeedHealthStore(redis)
            run_id = uuid4()
            assert await store.read(run_id) is None
            await redis.set(store.key(run_id), "not-json")
            assert await store.read(run_id) is None
            for lag, occurred_at in [
                (None, system_now_utc()),
                (0, system_now_utc() - timedelta(seconds=FEED_TTL_SECONDS + 1)),
            ]:
                await store.record(
                    LiveStreamHealthEvent.from_observation(
                        run_id, StreamHealth(0, 0, lag), occurred_at=occurred_at
                    )
                )
                assert await store.read(run_id) is None
            await store.record(
                LiveStreamHealthEvent.from_observation(
                    run_id, StreamHealth(0, 0, 10, True), occurred_at=system_now_utc()
                )
            )
            value = await store.read(run_id)
            assert value.book_stale and value.book_dispatch_lag_ms == 10

    asyncio.run(scenario())


def test_http_errors_and_admission_alerts_use_real_redis(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            app = FastAPI()
            app.state.redis = redis
            app.add_middleware(OperationalHttpMiddleware)
            app.add_exception_handler(ResourceLimitError, resource_limit_response)

            @app.get(
                "/fixture/error", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            def failed():
                return {}

            @app.get(
                "/fixture/rejection", status_code=status.HTTP_429_TOO_MANY_REQUESTS
            )
            def rejected():
                return {}

            @app.get("/fixture/capacity")
            def capacity():
                raise ResourceLimitError(
                    ResourceLimitCode.GLOBAL_CAPACITY, "fixture capacity"
                )

            @app.get("/fixture/ok")
            def ok():
                return {}

            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test"
            ) as client:
                for code, route in [
                    (AlertCode.API_ERRORS, "error"),
                    (AlertCode.ADMISSION_REJECTIONS, "rejection"),
                ]:
                    for _ in range(int(ALERT_DEFINITIONS[code].threshold)):
                        await client.get("/fixture/" + route)
                await client.get("/fixture/ok")
                capacity_response = await client.get("/fixture/capacity")
                assert (
                    capacity_response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
                )
                counters = ObservationCounters(redis)
                assert (
                    await counters.recent_count(Observation.HTTP_ERROR)
                    == ALERT_DEFINITIONS[AlertCode.API_ERRORS].threshold
                )
                assert (
                    await counters.recent_count(Observation.ADMISSION_REJECTION)
                    == ALERT_DEFINITIONS[AlertCode.ADMISSION_REJECTIONS].threshold + 1
                )
                monitor = OperationMonitor(
                    sessions, redis, lease_seconds=DEFAULT_LEASE_SECONDS
                )
                alerts = await monitor.tick()
                assert (
                    AlertCode.API_ERRORS in alerts
                    and AlertCode.ADMISSION_REJECTIONS in alerts
                )
                with patch.object(
                    ObservationCounters,
                    "increment",
                    AsyncMock(side_effect=RuntimeError("private-credential")),
                ):
                    assert (
                        await client.get("/fixture/error")
                    ).status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            await asyncio.to_thread(OPERATION_LOG.flush)

    asyncio.run(scenario())


def test_worker_presence_task_closes_resources_after_refresh_failure():
    async def scenario():
        redis = AsyncMock()
        presence = WorkerPresence(redis)
        attempted = asyncio.Event()

        async def refresh(*args):
            attempted.set()
            raise RuntimeError("private dependency detail")

        with patch.object(WorkerPresenceStore, "refresh", refresh):
            presence.start()
            await asyncio.wait_for(attempted.wait(), 1)
            await presence.stop()
        redis.delete.assert_awaited_once_with(
            WorkerPresenceStore.key(presence.worker_id)
        )
        redis.aclose.assert_awaited_once()

    asyncio.run(scenario())


def test_operational_log_sink_cannot_block_async_callers():

    async def scenario():
        entered, release = Event(), Event()

        def blocked_sink(*args):
            entered.set()
            release.wait(1)

        with patch("api.operations.observations.sink.logging.getLogger") as get_logger:
            get_logger.return_value.warning.side_effect = blocked_sink
            log = OperationLog()
            try:
                log.emit(FailureObservation(Observation.OBSERVER_FAILURE))
                assert await asyncio.to_thread(entered.wait, 1)
                started = monotonic()
                log.emit(FailureObservation(Observation.TELEMETRY_UNAVAILABLE))
                assert monotonic() - started < 0.2
            finally:
                release.set()
                await asyncio.to_thread(log.flush)

    asyncio.run(scenario())


def test_taskiq_callbacks_publish_presence_and_remove_it_on_shutdown(limits_services):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            state = TaskiqState()
            with patch(
                "api.operations.worker.configured_redis_url",
                return_value=limits_services[1],
            ):
                await start_worker_presence(state)
            try:
                async with asyncio.timeout(2):
                    while await WorkerPresenceStore(redis).count() == 0:
                        await asyncio.sleep(0.01)
            finally:
                await stop_worker_presence(state)
            assert await WorkerPresenceStore(redis).count() == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "headers", [None, status.HTTP_200_OK, status.HTTP_500_INTERNAL_SERVER_ERROR]
)
def test_http_exception_records_once_and_redacts_exception(headers):
    async def scenario():
        async def failed(scope, receive, send):
            if headers is not None:
                await send(
                    {"type": "http.response.start", "status": headers, "headers": []}
                )
            raise ValueError("private credential")

        middleware = OperationalHttpMiddleware(failed)
        with patch.object(
            middleware, "_record_http_operational_event", AsyncMock()
        ) as record:
            with pytest.raises(RuntimeError, match="^request execution failed$"):
                await middleware({"type": "http"}, AsyncMock(), AsyncMock())
            record.assert_awaited_once_with(
                {"type": "http"}, status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    asyncio.run(scenario())


def test_non_http_scope_passes_through_without_observation():
    async def scenario():
        app = AsyncMock()
        middleware = OperationalHttpMiddleware(app)
        scope, receive, send = {"type": "lifespan"}, AsyncMock(), AsyncMock()
        with patch.object(
            middleware, "_record_http_operational_event", AsyncMock()
        ) as record:
            await middleware(scope, receive, send)
            app.assert_awaited_once_with(scope, receive, send)
            record.assert_not_awaited()

    asyncio.run(scenario())


def test_taskiq_broker_registers_process_presence_lifecycle():
    assert start_worker_presence in broker.event_handlers[TaskiqEvents.WORKER_STARTUP]
    assert stop_worker_presence in broker.event_handlers[TaskiqEvents.WORKER_SHUTDOWN]


@pytest.mark.parametrize(
    "field,value",
    [
        ("book_stale", "false"),
        ("book_dispatch_lag_ms", "0"),
        ("book_dispatch_lag_ms", True),
    ],
)
def test_feed_adapter_rejects_coerced_json_types(limits_services, field, value):
    async def scenario():
        async with resource_services(limits_services) as (_, redis):
            store = FeedHealthStore(redis)
            run_id = uuid4()
            await store.record(
                LiveStreamHealthEvent.from_observation(
                    run_id, StreamHealth(0, 0, 0), occurred_at=system_now_utc()
                )
            )
            payload = json.loads(await redis.get(store.key(run_id)))
            payload["health"][field] = value
            await redis.set(store.key(run_id), json.dumps(payload))
            assert await store.read(run_id) is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "offset,available",
    [(FEED_TTL_SECONDS, True), (FEED_TTL_SECONDS + 1, False), (-1, False)],
)
def test_feed_freshness_boundary(offset, available):
    now = system_now_utc()
    observation = FeedObservation(
        observed_at=now - timedelta(seconds=offset),
        health=LiveStreamHealthEvent.from_observation(
            uuid4(), StreamHealth(0, 0, 0), occurred_at=now
        ).payload,
    )
    assert (observation.available_health(now) is not None) is available


def test_monitor_preserves_probe_independence_and_classifies_invalid_redis(
    limits_services,
):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            monitor = OperationMonitor(
                sessions, redis, lease_seconds=DEFAULT_LEASE_SECONDS
            )
            with patch.object(
                OperationMeasurements, "read", AsyncMock(side_effect=ConnectionError())
            ):
                alerts = await monitor.tick()
                assert AlertCode.DATABASE_UNAVAILABLE in alerts
                assert AlertCode.WORKER_UNAVAILABLE in alerts
                assert AlertCode.FEED_UNAVAILABLE not in alerts
            await redis.set(
                WORKER_KEY_PREFIX + "malformed",
                WORKER_PRESENCE_MARKER,
                ex=PRESENCE_TTL_SECONDS,
            )
            alerts = await monitor.tick()
            assert AlertCode.TELEMETRY_INVALID in alerts
            assert AlertCode.REDIS_UNAVAILABLE not in alerts

    asyncio.run(scenario())


@pytest.mark.parametrize("at_threshold", [False, True])
def test_monitor_wires_queue_storage_and_lag_thresholds(limits_services, at_threshold):
    async def scenario():
        async with resource_services(limits_services) as (sessions, redis):
            run_id = uuid4()
            lag = ALERT_DEFINITIONS[AlertCode.FEED_DEGRADED].threshold
            depth = ALERT_DEFINITIONS[AlertCode.QUEUE_CAPACITY].threshold
            free = ALERT_DEFINITIONS[AlertCode.STORAGE_LOW].threshold
            await FeedHealthStore(redis).record(
                LiveStreamHealthEvent.from_observation(
                    run_id,
                    StreamHealth(0, 0, int(lag if at_threshold else lag - 1)),
                    occurred_at=system_now_utc(),
                )
            )
            snapshot = DatabaseMeasurements(
                int(depth if at_threshold else depth - 1), 0, 0, 1, (run_id,), False
            )
            with (
                patch.object(
                    OperationMeasurements, "read", AsyncMock(return_value=snapshot)
                ),
                patch.object(
                    StorageProbe,
                    "free_bytes",
                    AsyncMock(return_value=free if at_threshold else free + 1),
                ),
            ):
                alerts = await OperationMonitor(
                    sessions, redis, lease_seconds=DEFAULT_LEASE_SECONDS
                ).tick()
            for code in (
                AlertCode.QUEUE_CAPACITY,
                AlertCode.STORAGE_LOW,
                AlertCode.FEED_DEGRADED,
            ):
                assert (code in alerts) is at_threshold

    asyncio.run(scenario())


def test_presence_ignores_key_disappearing_after_scan():
    async def scenario():
        redis = AsyncMock()

        async def keys(*args):
            yield WorkerPresenceStore.key(uuid4()).encode()

        redis.scan_iter = keys
        redis.eval.return_value = [None, -2]
        assert await WorkerPresenceStore(redis).count() == 0

    asyncio.run(scenario())


def test_log_overflow_reports_dropped_count_after_sink_recovers():
    entered, release = Event(), Event()
    recorded = []

    def sink(value):
        if not entered.is_set():
            entered.set()
            release.wait(2)
        recorded.append(json.loads(value))

    with patch("api.operations.observations.sink.logging.getLogger") as logger:
        logger.return_value.warning.side_effect = sink
        log = OperationLog()
        record = FailureObservation(Observation.OBSERVER_FAILURE)
        try:
            log.emit(record)
            assert entered.wait(1)
            for _ in range(MAX_QUEUED_OPERATION_RECORDS + 3):
                log.emit(record)
        finally:
            release.set()
        log.flush()
        log.emit(record)
        log.flush()
    assert recorded[-2]["event"] == Observation.LOG_OVERFLOW
    assert recorded[-2]["dropped_records"] == 3
    assert recorded[-1]["event"] == Observation.OBSERVER_FAILURE
