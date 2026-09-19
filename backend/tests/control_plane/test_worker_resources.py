"""Process ownership, isolation and bounded shutdown of worker resources."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import api.execution.worker.resources as resources_module
import pytest
from api.deployment.settings import DEFAULT_WORKER_DATABASE_POOL_SIZE, StartupSettings
from api.execution import worker
from api.execution.worker import process
from api.execution.worker.resources import WorkerResources
from taskiq import TaskiqState


@pytest.fixture
def resource_factory(monkeypatch):
    settings = StartupSettings(
        database_url="postgresql+asyncpg://localhost/worker_test",
        redis_url="redis://localhost:6379/1",
    )
    engine = SimpleNamespace(dispose=AsyncMock())
    redis = SimpleNamespace(aclose=AsyncMock())
    sessions = Mock()
    monkeypatch.setattr(
        resources_module, "WorkerLiveTelemetry", Mock(return_value=AsyncMock())
    )
    monkeypatch.setattr(
        resources_module, "TerminalWakePublisher", Mock(return_value=AsyncMock())
    )
    database = Mock(return_value=(engine, sessions))
    monkeypatch.setattr(resources_module, "create_worker_database", database)
    monkeypatch.setattr(resources_module.Redis, "from_url", Mock(return_value=redis))
    return SimpleNamespace(
        settings=settings,
        engine=engine,
        redis=redis,
        sessions=sessions,
        database=database,
    )


def test_concurrent_deliveries_share_engine_but_not_sessions(
    resource_factory, monkeypatch
):
    fixture = resource_factory

    async def scenario():
        resources = await WorkerResources.create(fixture.settings)
        created_sessions, running_sessions = [], []
        all_started = asyncio.Event()
        release = asyncio.Event()
        remaining = [uuid4() for _ in range(3)]

        @asynccontextmanager
        async def sessions():
            session = SimpleNamespace(commit=AsyncMock())
            created_sessions.append(session)
            yield session

        class Admission:
            def __init__(self, session):
                self.session = session

            async def next_eligible_queued_run_id(self):
                return remaining.pop() if remaining else None

        class Coordinator:
            def __init__(self, store, factory, writer, **kwargs):
                assert factory is sessions
                assert writer is resources.event_writer
                self.session = store.session

            async def execute(self, run_id):
                running_sessions.append(self.session)
                if len(running_sessions) == 3:
                    all_started.set()
                await release.wait()

        resources.sessions = sessions
        monkeypatch.setattr(worker, "RunAdmission", Admission)
        monkeypatch.setattr(
            worker, "RunStore", lambda session: SimpleNamespace(session=session)
        )
        monkeypatch.setattr(worker, "RunLifecycleCoordinator", Coordinator)
        tasks = [
            asyncio.create_task(worker.execute_run(uuid4(), resources=resources))
            for _ in range(3)
        ]
        await asyncio.wait_for(all_started.wait(), 1)
        assert len({id(session) for session in running_sessions}) == 3
        assert len({id(session) for session in created_sessions}) == len(
            created_sessions
        )
        fixture.database.assert_called_once_with(
            fixture.settings.database_url.get_secret_value(),
            pool_size=DEFAULT_WORKER_DATABASE_POOL_SIZE,
        )
        release.set()
        await asyncio.gather(*tasks)
        fixture.engine.dispose.assert_not_awaited()
        fixture.redis.aclose.assert_not_awaited()
        await asyncio.gather(resources.close(), resources.close())
        fixture.engine.dispose.assert_awaited_once()
        fixture.redis.aclose.assert_awaited_once()
        with pytest.raises(RuntimeError, match="shutting down"):
            await worker.execute_run(uuid4(), resources=resources)

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["complete", "fail", "cancel"])
def test_delivery_exit_leaves_other_delivery_usable(resource_factory, outcome):
    async def scenario():
        resources = await WorkerResources.create(resource_factory.settings)
        started = asyncio.Event()
        release = asyncio.Event()

        async def survivor():
            async with resources.delivery():
                started.set()
                await release.wait()
                assert not resources.closing

        async def departing():
            async with resources.delivery():
                if outcome == "fail":
                    raise RuntimeError("delivery failed")
                if outcome == "cancel":
                    raise asyncio.CancelledError

        task = asyncio.create_task(survivor())
        await started.wait()
        results = await asyncio.gather(departing(), return_exceptions=True)
        if outcome != "complete":
            assert isinstance(results[0], BaseException)
        resource_factory.engine.dispose.assert_not_awaited()
        release.set()
        await task
        await resources.close()

    asyncio.run(scenario())


def test_shutdown_awaits_delivery_cleanup_before_disposal(resource_factory):
    async def scenario():
        resources = await WorkerResources.create(resource_factory.settings)
        started, cleaning, finish_cleanup = (asyncio.Event() for _ in range(3))

        async def delivery():
            async with resources.delivery():
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    cleaning.set()
                    await finish_cleanup.wait()
                    resource_factory.engine.dispose.assert_not_awaited()

        task = asyncio.create_task(delivery())
        await started.wait()
        closing = asyncio.create_task(resources.close())
        await asyncio.wait_for(cleaning.wait(), 1)
        assert not closing.done()
        with pytest.raises(RuntimeError, match="shutting down"):
            async with resources.delivery():
                pass
        finish_cleanup.set()
        await closing
        assert task.cancelled()
        resource_factory.engine.dispose.assert_awaited_once()

    asyncio.run(scenario())


def test_partial_resource_construction_disposes_engine(resource_factory, monkeypatch):
    monkeypatch.setattr(
        resources_module.Redis,
        "from_url",
        Mock(side_effect=RuntimeError("unavailable")),
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(WorkerResources.create(resource_factory.settings))
    resource_factory.engine.dispose.assert_awaited_once()


def test_publisher_construction_failure_closes_both_resources(
    resource_factory, monkeypatch
):
    monkeypatch.setattr(
        resources_module,
        "RunEventWriter",
        Mock(side_effect=RuntimeError("unavailable")),
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(WorkerResources.create(resource_factory.settings))
    resource_factory.engine.dispose.assert_awaited_once()
    resource_factory.redis.aclose.assert_awaited_once()


def test_presence_startup_failure_closes_resources(resource_factory, monkeypatch):
    state = TaskiqState()
    monkeypatch.setattr(
        process.StartupSettings,
        "from_env",
        Mock(return_value=resource_factory.settings),
    )
    monkeypatch.setattr(
        process,
        "start_worker_presence",
        AsyncMock(side_effect=RuntimeError("presence failed")),
    )
    with pytest.raises(RuntimeError, match="presence failed"):
        asyncio.run(process.start_worker(state))
    resource_factory.engine.dispose.assert_awaited_once()
    resource_factory.redis.aclose.assert_awaited_once()


def test_missing_resources_fail_without_creating_pool(resource_factory):
    with pytest.raises(RuntimeError, match="not available"):
        process.worker_resources(TaskiqState())
    resource_factory.database.assert_not_called()


def test_delivery_timeout_reports_unclean_shutdown(resource_factory, monkeypatch):
    monkeypatch.setattr(resources_module, "WORKER_DELIVERY_CLEANUP_SECONDS", 0.01)

    async def scenario():
        resources = await WorkerResources.create(resource_factory.settings)
        started = asyncio.Event()

        async def delivery():
            async with resources.delivery():
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    await asyncio.Future()

        task = asyncio.create_task(delivery())
        await started.wait()
        with pytest.raises(ExceptionGroup, match="shutdown failed") as failure:
            await resources.close()
        assert any(
            isinstance(error, TimeoutError) for error in failure.value.exceptions
        )
        await asyncio.gather(task, return_exceptions=True)
        resource_factory.engine.dispose.assert_awaited_once()
        assert resources.closing

    asyncio.run(scenario())


def test_resource_timeout_still_attempts_engine_disposal(resource_factory, monkeypatch):
    monkeypatch.setattr(resources_module, "WORKER_RESOURCE_CLEANUP_SECONDS", 0.01)

    async def blocked_close():
        await asyncio.Future()

    resource_factory.redis.aclose.side_effect = blocked_close

    async def scenario():
        resources = await WorkerResources.create(resource_factory.settings)
        with pytest.raises(ExceptionGroup, match="shutdown failed"):
            await resources.close()
        resource_factory.engine.dispose.assert_awaited_once()
        assert resources.closing

    asyncio.run(scenario())


def test_failed_delivery_cleanup_is_reported_after_disposal(resource_factory):
    async def scenario():
        resources = await WorkerResources.create(resource_factory.settings)
        started = asyncio.Event()

        async def delivery():
            async with resources.delivery():
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    raise RuntimeError("terminal write failed")

        task = asyncio.create_task(delivery())
        await started.wait()
        with pytest.raises(ExceptionGroup, match="shutdown failed") as failure:
            await resources.close()
        assert str(failure.value.exceptions[0]) == "terminal write failed"
        assert task.done()
        resource_factory.engine.dispose.assert_awaited_once()
        resource_factory.redis.aclose.assert_awaited_once()

    asyncio.run(scenario())


def test_live_start_failure_closes_started_terminal_publisher(
    resource_factory, monkeypatch
):
    live = AsyncMock()
    live.start.side_effect = RuntimeError("live start failed")
    terminal = AsyncMock()
    monkeypatch.setattr(
        resources_module, "WorkerLiveTelemetry", Mock(return_value=live)
    )
    monkeypatch.setattr(
        resources_module, "TerminalWakePublisher", Mock(return_value=terminal)
    )
    with pytest.raises(RuntimeError, match="live start failed"):
        asyncio.run(WorkerResources.create(resource_factory.settings))
    terminal.start.assert_awaited_once()
    terminal.close.assert_awaited_once()
    live.close.assert_awaited_once()
    resource_factory.redis.aclose.assert_awaited_once()
    resource_factory.engine.dispose.assert_awaited_once()
