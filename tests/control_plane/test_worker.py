import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

import polybot_control_plane.execution.worker.lifecycle as worker_lifecycle
import polybot_control_plane.execution.worker.runtime as worker_runtime
from polybot.cli.observability.events import StreamHealth
from polybot.framework.base import BaseBot
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    INITIAL_DEFINITION_VERSION,
    WINNER_DEFINITION_ID,
)
from polybot_control_plane.events.contracts import DurableEvent, EventKind
from polybot_control_plane.execution.config import REDIS_URL_ENV, configured_redis_url
from polybot_control_plane.execution.worker.lifecycle import PAPER_RUN_FAILURE_REASON
from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.status import RunStatus


def test_worker_completes_normally_and_writes_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_claimed_bot(run, observer) -> None:
        return None

    async def poll(*args) -> None:
        await asyncio.Future()

    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
    monkeypatch.setattr(worker_lifecycle, "poll_stop_request_and_heartbeat", poll)
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        worker_lifecycle.execute_claimed_run_lifecycle(
            uuid4(), store, object(), writer
        )
    )

    assert store.transitions == [RunStatus.RUNNING, RunStatus.STOPPING]
    assert store.finished == [(RunStatus.STOPPED, None)]
    assert writer.events[-1].payload.status is RunStatus.STOPPED


def test_worker_writes_final_stream_health_before_terminal_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_claimed_bot(run, observer) -> None:
        await observer.start(run.config.to_bot_config())
        observer.emit(StreamHealth(1, 2, 3, False, 1.0, 4, 1))
        await observer.stop()

    async def poll(*args) -> None:
        await asyncio.Future()

    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
    monkeypatch.setattr(worker_lifecycle, "poll_stop_request_and_heartbeat", poll)
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        worker_lifecycle.execute_claimed_run_lifecycle(
            uuid4(), store, object(), writer
        )
    )

    assert [event.kind for event in writer.events] == [
        EventKind.STREAM_HEALTH,
        EventKind.RUN_LIFECYCLE,
    ]
    assert writer.events[-1].payload.status is RunStatus.STOPPED


def test_worker_cooperative_stop_finishes_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def run_claimed_bot(run, observer) -> None:
        started.set()
        await asyncio.Future()

    async def poll(run_id, bot_task, cooperative_stop, session_factory) -> None:
        await started.wait()
        cooperative_stop.set()
        bot_task.cancel()

    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
    monkeypatch.setattr(worker_lifecycle, "poll_stop_request_and_heartbeat", poll)
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        worker_lifecycle.execute_claimed_run_lifecycle(
            uuid4(), store, object(), writer
        )
    )

    assert store.finished == [(RunStatus.STOPPED, None)]
    assert writer.events[-1].payload.status is RunStatus.STOPPED


def test_worker_cancellation_finishes_interrupted_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> tuple[_FakeRunStore, _CollectingEventWriter]:
        started = asyncio.Event()

        async def run_claimed_bot(run, observer) -> None:
            started.set()
            await asyncio.Future()

        async def poll(*args) -> None:
            await asyncio.Future()

        monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
        monkeypatch.setattr(
            worker_lifecycle,
            "poll_stop_request_and_heartbeat",
            poll,
        )
        store = _FakeRunStore(_run())
        writer = _CollectingEventWriter()
        task = asyncio.create_task(
            worker_lifecycle.execute_claimed_run_lifecycle(
                uuid4(), store, object(), writer
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return store, writer

    store, writer = asyncio.run(scenario())

    assert store.finished == [(RunStatus.INTERRUPTED, None)]
    assert writer.events[-1].payload.status is RunStatus.INTERRUPTED


def test_worker_failure_detail_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "postgresql://user:secret@example.invalid/database"

    async def run_claimed_bot(run, observer) -> None:
        raise RuntimeError(secret)

    async def poll(*args) -> None:
        await asyncio.Future()

    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
    monkeypatch.setattr(worker_lifecycle, "poll_stop_request_and_heartbeat", poll)
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        worker_lifecycle.execute_claimed_run_lifecycle(
            uuid4(), store, object(), writer
        )
    )

    status, detail = store.finished[-1]
    assert status is RunStatus.FAILED
    assert detail == f"RuntimeError: {PAPER_RUN_FAILURE_REASON}"
    assert secret not in detail
    assert writer.events[-1].payload.status is RunStatus.FAILED


def test_worker_redelivery_does_not_restart_nonqueued_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def run_claimed_bot(run, observer) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
    store = _FakeRunStore(None)

    asyncio.run(
        worker_lifecycle.execute_claimed_run_lifecycle(
            uuid4(),
            store,
            object(),
            _CollectingEventWriter(),
        )
    )

    assert called is False
    assert store.finished == []


def test_worker_claim_failure_records_sanitized_failure() -> None:
    store = _ClaimFailureStore()
    writer = _CollectingEventWriter()

    asyncio.run(
        worker_lifecycle.execute_claimed_run_lifecycle(
            uuid4(), store, object(), writer
        )
    )

    assert store.finished == [
        (RunStatus.FAILED, f"RuntimeError: {PAPER_RUN_FAILURE_REASON}")
    ]
    assert writer.events[-1].payload.status is RunStatus.FAILED


def test_worker_completes_stop_that_wins_before_runtime_start() -> None:
    store = _PrestartStopStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        worker_lifecycle.execute_claimed_run_lifecycle(
            uuid4(), store, object(), writer
        )
    )

    assert store.transitions == [RunStatus.STOPPING]
    assert store.finished == [(RunStatus.STOPPED, None)]
    assert writer.events[-1].payload.status is RunStatus.STOPPED


def test_terminal_event_failure_does_not_change_run_outcome() -> None:
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter(fail=True)

    asyncio.run(
        worker_lifecycle._finish_run(
            uuid4(),
            store,
            writer,
            RunStatus.FAILED,
            failure_detail=PAPER_RUN_FAILURE_REASON,
        )
    )

    assert store.finished == [(RunStatus.FAILED, PAPER_RUN_FAILURE_REASON)]


def test_terminal_event_is_not_written_when_finish_loses_transition() -> None:
    store = _RejectedFinishStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        worker_lifecycle._finish_run(
            uuid4(),
            store,
            writer,
            RunStatus.FAILED,
        )
    )

    assert writer.events == []


def test_claimed_runtime_uses_exact_catalog_factory_and_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    entry = CATALOG[run.definition_id]
    received: list[tuple[object, object, object]] = []

    def factory(config):
        received.append(("factory", config, None))
        return BaseBot()

    async def run_bot(bot, config, *, observer) -> None:
        received.append((bot, config, observer))

    monkeypatch.setitem(CATALOG, run.definition_id, replace(entry, factory=factory))
    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)
    observer = object()

    asyncio.run(worker_runtime.run_claimed_bot(run, observer))

    _, factory_config, _ = received[0]
    bot, runtime_config, runtime_observer = received[1]
    assert isinstance(bot, BaseBot)
    assert factory_config is runtime_config
    assert runtime_config.name == run.config.name
    assert runtime_observer is observer


def test_redis_configuration_validates_environment_ingress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REDIS_URL_ENV, "http://localhost:6379")

    with pytest.raises(ValueError, match=REDIS_URL_ENV):
        configured_redis_url()

    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost/not-a-database")
    with pytest.raises(ValueError, match="numeric Redis database"):
        configured_redis_url()

    monkeypatch.setenv(REDIS_URL_ENV, "redis://:6379/0")
    with pytest.raises(ValueError, match="include a host"):
        configured_redis_url()

    monkeypatch.setenv(REDIS_URL_ENV, "redis://localhost:not-a-port/0")
    with pytest.raises(ValueError, match="invalid port"):
        configured_redis_url()

    monkeypatch.setenv(REDIS_URL_ENV, "rediss://cache.example:6380/2")
    assert configured_redis_url() == "rediss://cache.example:6380/2"


def test_worker_poll_transitions_stop_before_cancelling_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> tuple[bool, bool]:
        async def no_delay(seconds) -> None:
            return None

        store = _MonitorStore([RunStatus.STOP_REQUESTED])
        monkeypatch.setattr(worker_lifecycle.asyncio, "sleep", no_delay)
        monkeypatch.setattr(worker_lifecycle, "RunStore", lambda session: store)
        bot_task = asyncio.create_task(_wait_forever())
        cooperative_stop = asyncio.Event()
        await worker_lifecycle.poll_stop_request_and_heartbeat(
            uuid4(),
            bot_task,
            cooperative_stop,
            _SessionFactory(),
        )
        await asyncio.gather(bot_task, return_exceptions=True)
        return cooperative_stop.is_set(), store.stopping

    assert asyncio.run(scenario()) == (True, True)


def test_worker_poll_heartbeats_while_run_is_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> int:
        async def no_delay(seconds) -> None:
            return None

        store = _MonitorStore([RunStatus.RUNNING, None])
        monkeypatch.setattr(worker_lifecycle.asyncio, "sleep", no_delay)
        monkeypatch.setattr(worker_lifecycle, "RunStore", lambda session: store)
        bot_task = asyncio.create_task(_wait_forever())
        await worker_lifecycle.poll_stop_request_and_heartbeat(
            uuid4(),
            bot_task,
            asyncio.Event(),
            _SessionFactory(),
        )
        bot_task.cancel()
        await asyncio.gather(bot_task, return_exceptions=True)
        return store.heartbeat_count

    assert asyncio.run(scenario()) == 1


class _FakeRunStore:
    def __init__(self, run: RunRead | None) -> None:
        self.run = run
        self.transitions: list[RunStatus] = []
        self.finished: list[tuple[RunStatus, str | None]] = []

    async def claim(self, run_id, *, now):
        return self.run

    async def mark_running(self, run_id) -> bool:
        self.transitions.append(RunStatus.RUNNING)
        return True

    async def begin_completion(self, run_id) -> bool:
        self.transitions.append(RunStatus.STOPPING)
        return True

    async def finish(self, run_id, *, status, now, failure_detail=None) -> bool:
        self.finished.append((status, failure_detail))
        return True


class _CollectingEventWriter:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[DurableEvent] = []
        self._fail = fail

    async def append(self, event):
        self.events.append(event)
        if self._fail:
            raise RuntimeError("writer unavailable")
        return event


class _ClaimFailureStore(_FakeRunStore):
    def __init__(self) -> None:
        super().__init__(None)

    async def claim(self, run_id, *, now):
        raise RuntimeError("sensitive database detail")


class _PrestartStopStore(_FakeRunStore):
    async def mark_running(self, run_id) -> bool:
        return False

    async def status(self, run_id) -> RunStatus:
        return RunStatus.STOP_REQUESTED

    async def begin_stopping(self, run_id) -> bool:
        self.transitions.append(RunStatus.STOPPING)
        return True


class _RejectedFinishStore(_FakeRunStore):
    async def finish(self, run_id, *, status, now, failure_detail=None) -> bool:
        return False


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exception_type, exception, traceback):
        return False


class _MonitorStore:
    def __init__(self, statuses: list[RunStatus | None]) -> None:
        self._statuses = iter(statuses)
        self.stopping = False
        self.heartbeat_count = 0

    async def status(self, run_id):
        return next(self._statuses)

    async def begin_stopping(self, run_id) -> bool:
        self.stopping = True
        return True

    async def heartbeat(self, run_id, *, now) -> bool:
        self.heartbeat_count += 1
        return True


def _run() -> RunRead:
    return RunRead(
        id=uuid4(),
        definition_id=WINNER_DEFINITION_ID,
        definition_version=INITIAL_DEFINITION_VERSION,
        config=CATALOG[WINNER_DEFINITION_ID].parse_config({"name": "worker"}),
        status=RunStatus.STARTING,
        created_at=datetime.now(UTC),
    )


async def _wait_forever() -> None:
    await asyncio.Future()
