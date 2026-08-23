from datetime import UTC, datetime
import json
from pathlib import Path
import re
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

import polybot_control_plane.api.dependencies as dependencies_module
import polybot_control_plane.api.openapi as openapi_module
import polybot_control_plane.api.routes.events as events_routes
import polybot_control_plane.api.routes.run_lookup as run_lookup
import polybot_control_plane.api.routes.runs as runs_routes
from polybot_control_plane.api.app import app, create_app
from polybot_control_plane.api.contracts import HealthResponse
from polybot_control_plane.api.routes.events import (
    DURABLE_EVENT_SCHEMA_REFERENCE,
    LAST_EVENT_ID_HEADER,
    SSE_MEDIA_TYPE,
)
from polybot_control_plane.api.routes.health import SERVICE_UNAVAILABLE_DETAIL
from polybot_control_plane.api.routes.paths import (
    API_PREFIX,
    BOT_DEFINITIONS_PATH,
    HEALTH_PATH,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    RUNS_PATH,
    api_route_path,
)
from polybot_control_plane.api.routes.runs import RUN_LAUNCH_FAILURE_REASON
from polybot_control_plane.api.openapi import OPENAPI_OUTPUT_PATH
from polybot_control_plane.catalog.definitions import (
    INITIAL_DEFINITION_VERSION,
    WINNER_DEFINITION_ID,
)
from polybot_control_plane.events.contracts import (
    RunLifecycleEvent,
    RunStatusPayload,
)
from polybot_control_plane.events.ids import (
    MAX_DURABLE_EVENT_ID,
)
from polybot_control_plane.events.pagination import (
    DEFAULT_EVENT_PAGE_LIMIT,
    MAX_EVENT_PAGE_LIMIT,
)
from polybot_control_plane.events.store import StoredEventPage
from polybot_control_plane.runs.contracts import RunRead
from polybot_control_plane.runs.status import RunStatus


def test_launch_list_detail_and_ingress_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)

    launched = client.post(api_route_path(RUNS_PATH), json=_launch_body())

    assert launched.status_code == 202
    run = launched.json()
    assert run["definition_id"] == WINNER_DEFINITION_ID
    assert run["config"]["max_order_size"] == "2.500"
    assert launcher.run_ids == [run["id"]]
    assert client.get(api_route_path(RUNS_PATH)).json() == [run]
    assert client.get(api_route_path(RUN_PATH, run_id=run["id"])).json() == run

    stale = client.post(
        api_route_path(RUNS_PATH),
        json={**_launch_body(), "definition_version": 2},
    )
    untrusted = client.post(
        api_route_path(RUNS_PATH),
        json={
            **_launch_body(),
            "inputs": {"name": "unsafe", "private_key": "secret"},
        },
    )

    assert stale.status_code == 409
    assert untrusted.status_code == 422
    assert len(state.runs) == 1
    assert len(launcher.run_ids) == 1


def test_catalog_route_and_unknown_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)

    definitions = client.get(api_route_path(BOT_DEFINITIONS_PATH))
    missing = client.post(
        api_route_path(RUNS_PATH),
        json={**_launch_body(), "definition_id": "missing"},
    )

    assert definitions.status_code == 200
    assert WINNER_DEFINITION_ID in {
        definition["definition_id"] for definition in definitions.json()
    }
    assert missing.status_code == 404
    assert state.runs == {}
    assert launcher.run_ids == []


def test_queued_and_running_stop_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    redis = _Redis()
    client = _client(monkeypatch, state, redis=redis)
    queued_id = client.post(api_route_path(RUNS_PATH), json=_launch_body()).json()["id"]
    running_id = client.post(
        api_route_path(RUNS_PATH),
        json={
            **_launch_body(),
            "inputs": {**_launch_body()["inputs"], "name": "running"},
        },
    ).json()["id"]
    state.runs[running_id] = state.runs[running_id].model_copy(
        update={"status": RunStatus.RUNNING}
    )

    queued_first = client.post(api_route_path(RUN_STOP_PATH, run_id=queued_id))
    queued_second = client.post(api_route_path(RUN_STOP_PATH, run_id=queued_id))
    running_first = client.post(api_route_path(RUN_STOP_PATH, run_id=running_id))
    running_second = client.post(api_route_path(RUN_STOP_PATH, run_id=running_id))

    assert queued_first.json()["status"] == RunStatus.STOPPED
    assert queued_second.json()["status"] == RunStatus.STOPPED
    assert running_first.json()["status"] == RunStatus.STOP_REQUESTED
    assert running_second.json()["status"] == RunStatus.STOP_REQUESTED
    assert state.terminal_event_count == 1
    assert len(redis.published) == 1


def test_launcher_failure_is_visible_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "redis://user:secret@example.invalid/0"
    state = _State()
    redis = _Redis()
    client = _client(
        monkeypatch,
        state,
        redis=redis,
        launcher=_Launcher(error=RuntimeError(secret)),
    )

    response = client.post(api_route_path(RUNS_PATH), json=_launch_body())

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == RunStatus.FAILED
    assert run["failure_detail"] == f"RuntimeError: {RUN_LAUNCH_FAILURE_REASON}"
    assert secret not in run["failure_detail"]
    assert state.terminal_event_count == 1
    assert len(redis.published) == 1


def test_health_requires_postgres_and_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy = _client(monkeypatch, _State())
    assert healthy.get(api_route_path(HEALTH_PATH)).json() == HealthResponse().model_dump()

    unavailable_redis = _client(
        monkeypatch,
        _State(),
        redis=_Redis(ready=False),
    )
    response = unavailable_redis.get(api_route_path(HEALTH_PATH))
    assert response.status_code == 503
    assert response.json() == {"detail": SERVICE_UNAVAILABLE_DETAIL}

    unavailable_database = _client(
        monkeypatch,
        _State(database_ready=False),
    )
    response = unavailable_database.get(api_route_path(HEALTH_PATH))
    assert response.status_code == 503
    assert response.json() == {"detail": SERVICE_UNAVAILABLE_DETAIL}


def test_stream_prefers_last_event_id_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    cursors: list[int] = []

    async def stream(*args, after_event_id: int, **kwargs):
        cursors.append(after_event_id)
        yield ": complete\n\n"

    client = _client(monkeypatch, state)
    monkeypatch.setattr(events_routes, "stream_durable_events", stream)
    run_id = client.post(api_route_path(RUNS_PATH), json=_launch_body()).json()["id"]

    response = client.get(
        api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run_id),
        params={"after_event_id": 1},
        headers={LAST_EVENT_ID_HEADER: "2"},
    )

    assert response.status_code == 200
    assert cursors == [2]

    fallback = client.get(
        api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run_id),
        params={"after_event_id": 3},
    )
    assert fallback.status_code == 200
    assert cursors == [2, 3]


def test_missing_run_event_routes_and_pagination_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, _State())
    missing_id = uuid4()

    assert (
        client.post(api_route_path(RUN_STOP_PATH, run_id=missing_id)).status_code
        == 404
    )
    assert (
        client.get(api_route_path(RUN_EVENTS_PATH, run_id=missing_id)).status_code
        == 404
    )
    assert (
        client.get(
            api_route_path(RUN_EVENTS_STREAM_PATH, run_id=missing_id)
        ).status_code
        == 404
    )
    assert (
        client.get(
            api_route_path(RUN_EVENTS_PATH, run_id=missing_id),
            params={"before_event_id": -1},
        ).status_code
        == 422
    )
    assert (
        client.get(
            api_route_path(RUN_EVENTS_PATH, run_id=missing_id),
            params={"before_event_id": MAX_DURABLE_EVENT_ID + 1},
        ).status_code
        == 422
    )
    for invalid_limit in (0, MAX_EVENT_PAGE_LIMIT + 1):
        assert (
            client.get(
                api_route_path(RUN_EVENTS_PATH, run_id=missing_id),
                params={"limit": invalid_limit},
            ).status_code
            == 422
        )
    assert (
        client.get(
            api_route_path(RUN_EVENTS_STREAM_PATH, run_id=missing_id),
            headers={LAST_EVENT_ID_HEADER: str(MAX_DURABLE_EVENT_ID + 1)},
        ).status_code
        == 422
    )


def test_event_route_returns_bounded_newest_page_and_older_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    run_id = client.post(api_route_path(RUNS_PATH), json=_launch_body()).json()["id"]
    state.events.extend(
        (
            _lifecycle_event(run_id, 1, RunStatus.RUNNING),
            _lifecycle_event(run_id, 2, RunStatus.STOPPING),
            _lifecycle_event(run_id, 3, RunStatus.STOPPED),
        )
    )

    newest = client.get(
        api_route_path(RUN_EVENTS_PATH, run_id=run_id),
        params={"limit": 2},
    )
    older = client.get(
        api_route_path(RUN_EVENTS_PATH, run_id=run_id),
        params={"before_event_id": 2, "limit": 2},
    )

    assert newest.status_code == 200
    assert [event["id"] for event in newest.json()["events"]] == [2, 3]
    assert newest.json()["next_before_event_id"] == 2
    assert [event["id"] for event in older.json()["events"]] == [1]
    assert older.json()["next_before_event_id"] is None


def test_event_route_enforces_default_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    run_id = client.post(api_route_path(RUNS_PATH), json=_launch_body()).json()["id"]
    state.events.extend(
        _lifecycle_event(run_id, event_id, RunStatus.RUNNING)
        for event_id in range(1, DEFAULT_EVENT_PAGE_LIMIT + 2)
    )

    page = client.get(api_route_path(RUN_EVENTS_PATH, run_id=run_id)).json()

    assert len(page["events"]) == DEFAULT_EVENT_PAGE_LIMIT
    assert page["events"][0]["id"] == 2
    assert page["events"][-1]["id"] == DEFAULT_EVENT_PAGE_LIMIT + 1
    assert page["next_before_event_id"] == 2


def test_openapi_has_only_slice_12c_routes_and_is_current() -> None:
    document = app.openapi()

    assert all(path.startswith(API_PREFIX) for path in document["paths"])
    stream_schema = document["paths"][
        api_route_path(RUN_EVENTS_STREAM_PATH)
    ]["get"]["responses"]["200"]["content"][SSE_MEDIA_TYPE]["schema"]
    assert stream_schema == {"$ref": DURABLE_EVENT_SCHEMA_REFERENCE}
    expected = f"{json.dumps(document, indent=2, sort_keys=True)}\n"
    assert OPENAPI_OUTPUT_PATH.read_text() == expected
    assert Path(OPENAPI_OUTPUT_PATH).name == "control-plane.json"


def test_documented_route_inventory_matches_registration() -> None:
    architecture = Path("docs/web-control-plane-architecture.md").read_text()
    http_api = architecture.split("## HTTP API", 1)[1].split("## Frontend", 1)[0]
    documented_routes = set(
        re.findall(r"^- `(GET|POST) (/[^`?]+)", http_api, re.MULTILINE)
    )

    assert f"`{API_PREFIX}`" in architecture
    assert documented_routes == _openapi_route_methods(app.openapi())


def test_openapi_exporter_writes_production_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "control-plane.json"
    monkeypatch.setattr(openapi_module, "OPENAPI_OUTPUT_PATH", output_path)

    openapi_module.main()

    expected = f"{json.dumps(app.openapi(), indent=2, sort_keys=True)}\n"
    assert output_path.read_text() == expected


def test_application_lifespan_owns_default_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    redis = _Redis()
    session_factory = object()
    launcher = _Launcher()
    monkeypatch.setattr(dependencies_module, "configured_database_url", lambda: "db")
    monkeypatch.setattr(dependencies_module, "configured_redis_url", lambda: "redis")
    monkeypatch.setattr(dependencies_module, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(
        dependencies_module,
        "async_sessionmaker",
        lambda *args, **kwargs: session_factory,
    )
    monkeypatch.setattr(
        dependencies_module.Redis,
        "from_url",
        lambda url: redis,
    )
    monkeypatch.setattr(dependencies_module, "_default_launcher", lambda: launcher)
    application = create_app()

    with TestClient(application):
        assert application.state.session_factory is session_factory
        assert application.state.redis is redis
        assert application.state.launcher is launcher

    assert engine.disposed is True
    assert redis.closed is True

    injected_redis = _Redis()
    with TestClient(
        create_app(
            session_factory=object(),
            redis=injected_redis,
            launcher=_Launcher(),
        )
    ):
        pass
    assert injected_redis.closed is False


def _client(
    monkeypatch: pytest.MonkeyPatch,
    state: "_State",
    *,
    redis: "_Redis | None" = None,
    launcher: "_Launcher | None" = None,
) -> TestClient:
    monkeypatch.setattr(runs_routes, "RunStore", _RunStore)
    monkeypatch.setattr(runs_routes, "ApiRunLifecycle", _ApiRunLifecycle)
    monkeypatch.setattr(run_lookup, "RunStore", _RunStore)
    monkeypatch.setattr(events_routes, "EventStore", _EventStore)
    return TestClient(
        create_app(
            session_factory=_SessionFactory(state),
            redis=redis or _Redis(),
            launcher=launcher or _Launcher(),
        )
    )


def _launch_body() -> dict[str, object]:
    return {
        "definition_id": WINNER_DEFINITION_ID,
        "definition_version": INITIAL_DEFINITION_VERSION,
        "inputs": {"name": "winner", "max_order_size": "2.500"},
    }


def _lifecycle_event(
    run_id: str,
    event_id: int,
    status: RunStatus,
) -> RunLifecycleEvent:
    return RunLifecycleEvent(
        id=event_id,
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=RunStatusPayload(status=status),
    )


class _State:
    def __init__(self, *, database_ready: bool = True) -> None:
        self.database_ready = database_ready
        self.runs: dict[str, RunRead] = {}
        self.next_event_id = 1
        self.terminal_event_count = 0
        self.events: list[RunLifecycleEvent] = []


class _SessionFactory:
    def __init__(self, state: _State) -> None:
        self.state = state

    def __call__(self) -> "_Session":
        return _Session(self.state)


class _Session:
    def __init__(self, state: _State) -> None:
        self.state = state

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        if not self.state.database_ready:
            raise RuntimeError("database unavailable")


class _RunStore:
    def __init__(self, session: _Session) -> None:
        self.state = session.state

    async def create(self, *, definition_id, definition_version, config) -> RunRead:
        run = RunRead(
            id=uuid4(),
            definition_id=definition_id,
            definition_version=definition_version,
            config=config,
            status=RunStatus.QUEUED,
            created_at=datetime.now(UTC),
        )
        self.state.runs[str(run.id)] = run
        return run

    async def read(self, run_id) -> RunRead | None:
        return self.state.runs.get(str(run_id))

    async def list(self) -> tuple[RunRead, ...]:
        return tuple(reversed(tuple(self.state.runs.values())))


class _EventStore:
    def __init__(self, session: _Session) -> None:
        self.state = session.state

    async def read_page(self, run_id, *, before_event_id, limit):
        events = tuple(
            event
            for event in self.state.events
            if event.run_id == run_id
            and event.id is not None
            and (before_event_id is None or event.id < before_event_id)
        )
        descending = tuple(reversed(events))
        has_more = len(descending) > limit
        page = descending[:limit]
        return StoredEventPage(
            events=tuple(reversed(page)),
            next_before_event_id=page[-1].id if has_more else None,
        )


class _ApiRunLifecycle:
    def __init__(self, session: _Session) -> None:
        self.state = session.state

    async def request_stop(self, run_id, *, now):
        key = str(run_id)
        run = self.state.runs.get(key)
        if run is None:
            return None
        event_id = None
        if run.status is RunStatus.QUEUED:
            run = run.model_copy(
                update={"status": RunStatus.STOPPED, "ended_at": now}
            )
            event_id = self._terminal_event_id()
        elif run.status in {RunStatus.STARTING, RunStatus.RUNNING}:
            run = run.model_copy(update={"status": RunStatus.STOP_REQUESTED})
        self.state.runs[key] = run
        return run, event_id

    async def fail_launch(self, run_id, *, now, failure_detail):
        key = str(run_id)
        run = self.state.runs[key].model_copy(
            update={
                "status": RunStatus.FAILED,
                "ended_at": now,
                "failure_detail": failure_detail,
            }
        )
        self.state.runs[key] = run
        return run, self._terminal_event_id()

    def _terminal_event_id(self) -> int:
        event_id = self.state.next_event_id
        self.state.next_event_id += 1
        self.state.terminal_event_count += 1
        return event_id


class _Launcher:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.run_ids: list[str] = []

    async def launch(self, run_id) -> None:
        self.run_ids.append(str(run_id))
        if self.error is not None:
            raise self.error


class _Redis:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))

    async def ping(self) -> bool:
        return self.ready

    async def aclose(self) -> None:
        self.closed = True


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def _openapi_route_methods(
    document: dict[str, object],
) -> set[tuple[str, str]]:
    paths = document["paths"]
    assert isinstance(paths, dict)
    return {
        (method.upper(), path.removeprefix(API_PREFIX))
        for path, path_item in paths.items()
        for method, operation in path_item.items()
        if isinstance(operation, dict) and "operationId" in operation
    }
