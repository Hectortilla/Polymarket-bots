"""Real database contention and Taskiq shutdown with process-owned resources."""

import asyncio
from contextlib import AsyncExitStack
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

import api.execution.worker.resources as resources_module
import pytest
from api.deployment.settings import StartupSettings
from api.events.kinds import EventKind
from api.events.store import EventStore
from api.execution.policy import TASKIQ_SHUTDOWN_SECONDS, WORKER_STOP_GRACE_SECONDS
from api.execution.taskiq_app import execute_run_task
from api.execution.worker import lifecycle, process
from api.execution.worker.resources import WorkerResources
from api.runs.status import RunStatus
from api.runs.store import RunStore
from sqlalchemy import event, text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from taskiq import TaskiqEvents, TaskiqMessage
from taskiq.receiver import Receiver
from taskiq_redis import RedisStreamBroker

from control_plane.limits_fixtures import account_bot, queue_run
from control_plane.limits_fixtures import (
    limits_services as limits_services,  # noqa: PLC0414
)


@pytest.mark.postgres
def test_shared_worker_pool_bounds_connections_and_releases_waiters(
    limits_services, monkeypatch
):
    async def scenario():
        settings = StartupSettings(
            database_url=limits_services[0],
            redis_url=limits_services[1],
            worker_database_pool_size=2,
        )
        captured = []
        create_database = resources_module.create_worker_database

        def capture(*args, **kwargs):
            engine, sessions = create_database(*args, **kwargs)
            captured.append(engine)
            return engine, sessions

        monkeypatch.setattr(resources_module, "create_worker_database", capture)
        resources = await WorkerResources.create(settings)
        engine = captured[0]
        backend_pids = set()
        connections_created = []
        event.listen(
            engine.sync_engine,
            "connect",
            lambda connection, record: connections_created.append(connection),
        )

        async def operation():
            async with resources.delivery(), resources.sessions() as session:
                backend_pids.add(await session.scalar(text("select pg_backend_pid()")))

        try:
            async with AsyncExitStack() as held:
                first = await held.enter_async_context(resources.sessions())
                second = await held.enter_async_context(resources.sessions())
                await first.execute(text("select 1"))
                await second.execute(text("select 1"))
                waiter = asyncio.create_task(operation())
                done, pending = await asyncio.wait({waiter}, timeout=0.05)
                assert not done and pending
                assert len(connections_created) == settings.worker_database_pool_size
                await first.close()
                await asyncio.wait_for(waiter, 2)
            await asyncio.gather(*(operation() for _ in range(100)))
            assert len(captured) == 1
            assert len(connections_created) == settings.worker_database_pool_size
            assert len(backend_pids) <= settings.worker_database_pool_size
            assert engine.pool.checkedout() == 0
        finally:
            await resources.close()
        assert engine.pool.checkedin() == 0

    asyncio.run(scenario())


@pytest.mark.postgres
def test_pool_exhaustion_times_out_without_overflow(limits_services):
    async def scenario():
        settings = StartupSettings(
            database_url=limits_services[0],
            redis_url=limits_services[1],
            worker_database_pool_size=2,
        )
        resources = await WorkerResources.create(settings)
        try:
            async with AsyncExitStack() as held:
                for _ in range(settings.worker_database_pool_size):
                    session = await held.enter_async_context(resources.sessions())
                    await session.execute(text("select 1"))
                async with resources.sessions() as session:
                    with pytest.raises(PoolTimeout):
                        await session.execute(text("select 1"))
            async with resources.sessions() as session:
                assert await session.scalar(text("select 1")) == 1
        finally:
            await resources.close()

    asyncio.run(scenario())


@pytest.mark.postgres
def test_taskiq_context_and_shutdown_preserve_terminal_writes(
    limits_services, monkeypatch
):
    async def scenario():
        settings = StartupSettings(
            database_url=limits_services[0],
            redis_url=limits_services[1],
            worker_database_pool_size=2,
            heartbeat_seconds=0.05,
        )
        monkeypatch.setattr(
            process.StartupSettings, "from_env", Mock(return_value=settings)
        )
        broker = RedisStreamBroker(
            limits_services[1], queue_name=f"pool-test-{uuid4()}"
        )
        broker.is_worker_process = True
        broker.on_event(TaskiqEvents.WORKER_STARTUP)(process.start_worker)
        broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)(process.stop_worker)
        # Use the production handler and dependency resolution without importing
        # a second copy of the application broker or contacting vendor services.
        broker.register_task(
            execute_run_task.original_func, task_name=execute_run_task.task_name
        )
        started = asyncio.Event()
        cleaned = []
        running = []

        async def runtime(run, observer, **kwargs):
            await observer.start(run.config.to_bot_config())
            running.append(run.id)
            if len(running) == 2:
                started.set()
            try:
                await asyncio.Future()
            finally:
                await observer.stop()
                cleaned.append(run.id)

        monkeypatch.setattr(lifecycle, "run_claimed_bot", runtime)
        await broker.startup()
        resources = process.worker_resources(broker.state)
        receiver = Receiver(broker, max_async_tasks=2)
        callbacks = []
        try:
            runs = []
            for _ in range(2):
                _, bot = await account_bot(resources.sessions)
                runs.append(await queue_run(resources.sessions, bot))
            for run in runs:
                message = TaskiqMessage(
                    task_id=str(uuid4()),
                    task_name=execute_run_task.task_name,
                    labels={},
                    args=[str(run.id)],
                    kwargs={},
                )
                callbacks.append(
                    asyncio.create_task(
                        receiver.callback(broker.formatter.dumps(message).message)
                    )
                )
            await asyncio.wait_for(started.wait(), 5)
            # Let the real monitors share the same small pool with live/durable
            # observer work before Taskiq invokes its shutdown handlers.
            await asyncio.sleep(0.3)
            before = monotonic()
            await asyncio.wait_for(broker.shutdown(), TASKIQ_SHUTDOWN_SECONDS)
            assert monotonic() - before < WORKER_STOP_GRACE_SECONDS
            await asyncio.gather(*callbacks, return_exceptions=True)
            assert sorted(cleaned) == sorted(run.id for run in runs)
            with pytest.raises(RuntimeError, match="not available"):
                process.worker_resources(broker.state)
            # The disposed shared engine can be inspected through a separately
            # owned test engine; production never reuses the closed bundle.
            engine, sessions = resources_module.create_worker_database(
                limits_services[0]
            )
            try:
                async with sessions() as session:
                    for run in runs:
                        restored = await RunStore(session).read(run.id)
                        assert restored.status is RunStatus.INTERRUPTED
                        assert restored.heartbeat_at > run.created_at
                        events = await EventStore(session).read(run.id)
                        assert events[-1].kind is EventKind.RUN_LIFECYCLE
                        assert events[-1].payload.status is RunStatus.INTERRUPTED
                        assert any(
                            item.kind is EventKind.CHART_SAMPLE for item in events[:-1]
                        )
            finally:
                await engine.dispose()
        finally:
            for callback in callbacks:
                if not callback.done():
                    callback.cancel()
            await asyncio.gather(*callbacks, return_exceptions=True)
            if not resources.closing:
                await broker.shutdown()

    asyncio.run(scenario())
