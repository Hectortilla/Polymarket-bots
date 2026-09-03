import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import polybot_control_plane.execution.worker.lifecycle as worker_lifecycle
import polybot_control_plane.execution.worker.runtime as worker_runtime
from control_plane.graph_fixtures import threshold_buy_graph
from polybot.cli.observability.broker import ObservableBroker
from polybot.cli.observability.events import PortfolioSnapshot, StreamHealth
from polybot.execution.broker import Broker
from polybot.execution.paper import PaperBroker
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import FillRejectReason, OrderStatus
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.runner import BotRunner
from polybot.polymarket.markets import Market, MarketOutcome
from polybot_control_plane.bots.revisions import FIRST_GRAPH_REVISION_NUMBER
from polybot_control_plane.catalog.definitions import (
    CATALOG,
    NODE_BASED_DEFINITION_ID,
    WINNER_DEFINITION_ID,
)
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.catalog.graphs.values import GraphNodeType
from polybot_control_plane.catalog.node_based.bot import NodeBasedBot
from polybot_control_plane.events.contracts import DurableEvent
from polybot_control_plane.events.kinds import EventKind
from polybot_control_plane.events.observer import WebRuntimeObserver
from polybot_control_plane.execution.config import REDIS_URL_ENV, configured_redis_url
from polybot_control_plane.execution.worker.lifecycle import PAPER_RUN_FAILURE_REASON
from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.status import RunStatus


def _coordinator(store, writer, session_factory=object()):
    return worker_lifecycle.RunLifecycleCoordinator(
        store,
        session_factory,
        writer,
    )


def test_worker_completes_normally_and_writes_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_claimed_bot(run, observer) -> None:
        return None

    async def poll(*args) -> None:
        await asyncio.Future()

    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
    monkeypatch.setattr(
        worker_lifecycle.RunLifecycleCoordinator,
        "_poll_stop_request_and_heartbeat",
        poll,
    )
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        _coordinator(store, writer).execute(uuid4())
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
    monkeypatch.setattr(
        worker_lifecycle.RunLifecycleCoordinator,
        "_poll_stop_request_and_heartbeat",
        poll,
    )
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        _coordinator(store, writer).execute(uuid4())
    )

    assert [event.kind for event in writer.events] == [
        EventKind.CHART_SAMPLE,
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

    async def poll(self, run_id, bot_task, cooperative_stop) -> None:
        await started.wait()
        cooperative_stop.set()
        bot_task.cancel()

    monkeypatch.setattr(worker_lifecycle, "run_claimed_bot", run_claimed_bot)
    monkeypatch.setattr(
        worker_lifecycle.RunLifecycleCoordinator,
        "_poll_stop_request_and_heartbeat",
        poll,
    )
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        _coordinator(store, writer).execute(uuid4())
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
            worker_lifecycle.RunLifecycleCoordinator,
            "_poll_stop_request_and_heartbeat",
            poll,
        )
        store = _FakeRunStore(_run())
        writer = _CollectingEventWriter()
        task = asyncio.create_task(
            _coordinator(store, writer).execute(uuid4())
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
    monkeypatch.setattr(
        worker_lifecycle.RunLifecycleCoordinator,
        "_poll_stop_request_and_heartbeat",
        poll,
    )
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        _coordinator(store, writer).execute(uuid4())
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
        _coordinator(store, _CollectingEventWriter()).execute(uuid4())
    )

    assert called is False
    assert store.finished == []


def test_worker_claim_failure_records_sanitized_failure() -> None:
    store = _ClaimFailureStore()
    writer = _CollectingEventWriter()

    asyncio.run(
        _coordinator(store, writer).execute(uuid4())
    )

    assert store.finished == [
        (RunStatus.FAILED, f"RuntimeError: {PAPER_RUN_FAILURE_REASON}")
    ]
    assert writer.events[-1].payload.status is RunStatus.FAILED


def test_worker_completes_stop_that_wins_before_runtime_start() -> None:
    store = _PrestartStopStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        _coordinator(store, writer).execute(uuid4())
    )

    assert store.transitions == [RunStatus.STOPPING]
    assert store.finished == [(RunStatus.STOPPED, None)]
    assert writer.events[-1].payload.status is RunStatus.STOPPED


def test_terminal_event_failure_does_not_change_run_outcome() -> None:
    store = _FakeRunStore(_run())
    writer = _CollectingEventWriter(fail=True)

    asyncio.run(
        _coordinator(store, writer)._finish_run(
            uuid4(),
            RunStatus.FAILED,
            failure_detail=PAPER_RUN_FAILURE_REASON,
        )
    )

    assert store.finished == [(RunStatus.FAILED, PAPER_RUN_FAILURE_REASON)]


def test_terminal_event_is_not_written_when_finish_loses_transition() -> None:
    store = _RejectedFinishStore(_run())
    writer = _CollectingEventWriter()

    asyncio.run(
        _coordinator(store, writer)._finish_run(
            uuid4(),
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
    assert factory_config == run.config.to_bot_config()
    assert runtime_config.name == run.config.name
    assert runtime_observer is observer


def test_claimed_runtime_executes_an_actual_non_node_catalog_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run()
    executed: list[BaseBot] = []

    async def run_bot(bot, config, *, observer) -> None:
        executed.append(bot)
        context = BotContext(
            config=config,
            broker=AsyncMock(spec=Broker),
            markets=AsyncMock(),
            books=AsyncMock(),
            wallet_activity=AsyncMock(),
            clock=_FixedClock(1_000),
        )
        await bot.on_start(context)
        await bot.on_stop(context)

    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)

    asyncio.run(worker_runtime.run_claimed_bot(run, object()))

    assert len(executed) == 1
    assert type(executed[0]) is type(
        CATALOG[WINNER_DEFINITION_ID].create_bot(run.config.to_bot_config(), None)
    )


def test_claimed_runtime_rejects_an_unknown_catalog_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_bot = AsyncMock()
    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)
    run = _run().model_copy(update={"definition_id": "missing-definition"})

    with pytest.raises(RuntimeError, match="definition is no longer available"):
        asyncio.run(worker_runtime.run_claimed_bot(run, object()))

    run_bot.assert_not_awaited()


@pytest.mark.parametrize(
    ("definition_id", "graph"),
    (
        (WINNER_DEFINITION_ID, NodeGraph.model_validate(threshold_buy_graph())),
        (NODE_BASED_DEFINITION_ID, None),
    ),
    ids=("ordinary-definition-with-graph", "graph-definition-without-graph"),
)
def test_claimed_runtime_rejects_inconsistent_graph_contract_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    definition_id: str,
    graph: NodeGraph | None,
) -> None:
    run_bot = AsyncMock()
    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)
    config = (
        CATALOG[NODE_BASED_DEFINITION_ID].parse_config(
            {"name": "missing-graph", "market_slugs": ["market"]}
        )
        if definition_id == NODE_BASED_DEFINITION_ID
        else CATALOG[WINNER_DEFINITION_ID].parse_config({"name": "forbidden-graph"})
    )
    run = _run().model_copy(
        update={"definition_id": definition_id, "config": config, "graph": graph}
    )

    with pytest.raises(ValueError, match="graph is (forbidden|required)"):
        asyncio.run(worker_runtime.run_claimed_bot(run, object()))

    run_bot.assert_not_awaited()


def test_node_based_action_graph_submits_each_matching_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = CATALOG[NODE_BASED_DEFINITION_ID]
    config = entry.parse_config(
        {
            "name": "node-observer",
            "market_slugs": ["example-market"],
        }
    )
    graph = NodeGraph.model_validate(threshold_buy_graph())
    run = _run().model_copy(
        update={
            "definition_id": NODE_BASED_DEFINITION_ID,
            "config": config,
            "bot_graph_revision_id": uuid4(),
            "graph_revision": FIRST_GRAPH_REVISION_NUMBER,
            "graph": graph,
        }
    )
    broker = AsyncMock(spec=Broker)
    received: list[tuple[BaseBot, object]] = []

    async def run_bot(bot, runtime_config, *, observer) -> None:
        received.append((bot, runtime_config))
        context = BotContext(
            config=runtime_config,
            broker=broker,
            markets=AsyncMock(),
            books=AsyncMock(),
            wallet_activity=AsyncMock(),
            clock=_FixedClock(1_000),
        )
        await bot.on_start(context)
        await bot.on_book(
            context,
            BookSnapshot(
                token_id="token",
                bids=(BookLevel(Decimal("0.49"), Decimal(10)),),
                asks=(BookLevel(Decimal("0.50"), Decimal(10)),),
                received_at_ms=1_000,
            ),
        )
        await bot.on_stop(context)

    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)

    asyncio.run(worker_runtime.run_claimed_bot(run, object()))

    bot, runtime_config = received[0]
    assert isinstance(bot, NodeBasedBot)
    assert runtime_config.stream_rules == config.stream_rules
    assert not hasattr(runtime_config, "graph")
    assert any(
        node.type == GraphNodeType.BROKER_ACTION for node in graph.nodes
    )
    assert broker.submit.await_count == 1
    assert broker.submit.await_args.args[0].token_id == "token"


def test_node_based_runtime_uses_paper_broker_and_durable_event_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = CATALOG[NODE_BASED_DEFINITION_ID]
    config = entry.parse_config(
        {
            "name": "node-events",
            "market_slugs": ["example-market"],
        }
    )
    graph = NodeGraph.model_validate(threshold_buy_graph())
    run = _run().model_copy(
        update={
            "definition_id": NODE_BASED_DEFINITION_ID,
            "config": config,
            "bot_graph_revision_id": uuid4(),
            "graph_revision": FIRST_GRAPH_REVISION_NUMBER,
            "graph": graph,
        }
    )
    writer = _CollectingEventWriter()
    observer = WebRuntimeObserver(run.id, writer)

    outcomes: list[DispatchOutcome] = []
    paper_brokers: list[PaperBroker] = []

    class MutableBooks:
        def __init__(self, snapshot: BookSnapshot) -> None:
            self.snapshot = snapshot

        async def latest(self, token_id: str) -> BookSnapshot:
            return self.snapshot

    class StaticMarkets:
        async def find_by_slug(self, slug: str) -> Market:
            return Market(
                condition_id="condition",
                slug="example-market",
                question="Test market",
                minimum_tick_size=Decimal("0.01"),
                minimum_order_size=Decimal(1),
                neg_risk=False,
                fee_rate=Decimal(0),
                outcomes=(
                    MarketOutcome("Yes", "token"),
                    MarketOutcome("No", "other-token"),
                ),
                active=True,
                closed=False,
                order_book_enabled=True,
                accepting_orders=True,
            )

    async def run_bot(bot, runtime_config, *, observer) -> None:
        valid_book = BookSnapshot(
            token_id="token",
            bids=(BookLevel(Decimal("0.49"), Decimal(10)),),
            asks=(BookLevel(Decimal("0.50"), Decimal(10)),),
            received_at_ms=10_000,
            market_slug="example-market",
            condition_id="condition",
        )
        books = MutableBooks(valid_book)
        paper_broker = PaperBroker(
            runtime_config,
            books,
            StaticMarkets(),
            sleep_fn=lambda _: asyncio.sleep(0),
            now_ms_fn=lambda: 10_000,
        )
        paper_brokers.append(paper_broker)
        await observer.start(runtime_config)
        try:
            context = BotContext(
                config=runtime_config,
                broker=ObservableBroker(
                    paper_broker,
                    observer,
                    lambda: PortfolioSnapshot.from_paper(paper_broker.portfolio),
                ),
                markets=StaticMarkets(),
                books=books,
                wallet_activity=AsyncMock(),
                clock=_FixedClock(10_000),
            )
            runner = BotRunner(bot, context, now_ms_fn=lambda: 10_000)
            outcomes.append(await runner.dispatch_book(valid_book))
            books.snapshot = replace(valid_book, received_at_ms=0)
            outcomes.append(await runner.dispatch_book(valid_book))
        finally:
            await observer.stop()

    monkeypatch.setattr(worker_runtime, "run_bot", run_bot)

    asyncio.run(worker_runtime.run_claimed_bot(run, observer))

    broker_events = [
        event
        for event in writer.events
        if event.kind in {EventKind.BROKER_ORDER, EventKind.BROKER_FILL}
    ]
    fills = [
        event.payload
        for event in broker_events
        if event.kind is EventKind.BROKER_FILL
    ]

    assert outcomes == [DispatchOutcome.accepted_event()] * 2
    assert [event.kind for event in broker_events] == [
        EventKind.BROKER_ORDER,
        EventKind.BROKER_FILL,
        EventKind.BROKER_ORDER,
        EventKind.BROKER_FILL,
    ]
    assert fills[0].fill.status is OrderStatus.FILLED
    assert fills[0].portfolio is not None
    assert fills[0].portfolio.positions[0].size == Decimal("1.250")
    assert fills[1].fill.status is OrderStatus.REJECTED
    assert fills[1].fill.reject_reason is FillRejectReason.BOOK_STALE
    assert fills[1].portfolio == fills[0].portfolio
    assert paper_brokers[0].portfolio.position("token").size == Decimal("1.250")


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
        await _coordinator(
            _FakeRunStore(None),
            _CollectingEventWriter(),
            _SessionFactory(),
        )._poll_stop_request_and_heartbeat(
            uuid4(),
            bot_task,
            cooperative_stop,
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
        await _coordinator(
            _FakeRunStore(None),
            _CollectingEventWriter(),
            _SessionFactory(),
        )._poll_stop_request_and_heartbeat(
            uuid4(),
            bot_task,
            asyncio.Event(),
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


class _FixedClock:
    def __init__(self, now_ms: int) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms

    async def sleep(self, seconds: float) -> None:
        pass


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
        bot_id=uuid4(),
        definition_id=WINNER_DEFINITION_ID,
        config=CATALOG[WINNER_DEFINITION_ID].parse_config({"name": "worker"}),
        status=RunStatus.STARTING,
        created_at=datetime.now(UTC),
    )


async def _wait_forever() -> None:
    await asyncio.Future()
