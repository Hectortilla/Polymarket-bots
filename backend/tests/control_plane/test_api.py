import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import api.http.dependencies as dependencies_module
import api.http.openapi as openapi_module
import api.http.routes.bots.run_launch as bot_run_routes
import api.http.routes.bots.saved_bot as saved_bot_routes
import api.http.routes.events as events_routes
import api.http.routes.run_lookup as run_lookup
import api.http.routes.runs as runs_routes
import pytest
from api.bots.contracts import BotCreate, BotRead, BotUpdate
from api.bots.models import BotRow
from api.catalog.contracts import BotDefinitionDescriptor
from api.catalog.definitions import (
    NODE_BASED_DEFINITION_ID,
    WINNER_DEFINITION_ID,
)
from api.catalog.graphs.catalog import GraphNodeCatalog
from api.events.contracts import (
    ChartSampleEvent,
    ChartSamplePayload,
    DurableEvent,
    RunFailureEvent,
    RunFailurePayload,
    RunLifecycleEvent,
    RunStatusPayload,
)
from api.events.contracts.payloads.chart import EquityChartPointPayload
from api.events.ids import (
    FIRST_EVENT_CURSOR,
    MAX_DURABLE_EVENT_ID,
)
from api.events.pagination import (
    DEFAULT_EVENT_PAGE_LIMIT,
    MAX_EVENT_PAGE_LIMIT,
    MIN_EVENT_PAGE_LIMIT,
    next_event_page_cursor,
)
from api.events.store import StoredEventPage
from api.events.views import EventView
from api.http.app import app
from api.http.contracts import HealthResponse
from api.http.errors import SERVICE_UNAVAILABLE_DETAIL
from api.http.openapi import OPENAPI_OUTPUT_PATH
from api.http.protocol import IDEMPOTENCY_KEY_HEADER, IDEMPOTENCY_RECOVERY_HEADER
from api.http.routes.bots.market_validation import (
    MARKET_SELECTION_UNAVAILABLE_DETAIL,
)
from api.http.routes.events import (
    DURABLE_EVENT_SCHEMA_REFERENCE,
    LAST_EVENT_ID_HEADER,
    SSE_MEDIA_TYPE,
)
from api.http.routes.paths import (
    API_PREFIX,
    BOT_DEFINITIONS_PATH,
    BOT_PATH,
    BOT_RUNS_PATH,
    BOTS_PATH,
    HEALTH_PATH,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    RUNS_PATH,
    api_route_path,
)
from api.runs.contracts import PaperRunConfig, RunRead
from api.runs.failures import LaunchAttemptUnavailable
from api.runs.models import RunRow
from api.runs.status import RunStatus
from fastapi import status
from polybot.performance.contracts.valuation_status import ValuationStatus

from control_plane.auth_fixtures import TEST_USER_ID
from control_plane.auth_fixtures import authenticated_test_client as TestClient
from control_plane.auth_fixtures import create_authenticated_app as create_app
from control_plane.graph_fixtures import threshold_buy_graph
from control_plane.market_fixtures import market_discovery
from control_plane.run_contract_fixture import (
    FRONTEND_RUN_CONTRACT_PATH,
    frontend_run_contract,
)


def test_launch_list_detail_and_ingress_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)

    bot = _create_bot(client)
    launched = client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]))

    assert launched.status_code == status.HTTP_202_ACCEPTED
    run = launched.json()
    assert run["definition_id"] == WINNER_DEFINITION_ID
    assert run["bot_id"] == bot["id"]
    assert "definition_version" not in run
    assert run["config"]["max_order_size"] == "2.500"
    assert run["config"]["graph"] is None
    assert launcher.run_ids == [run["id"]]
    assert client.get(api_route_path(RUNS_PATH)).json() == [run]
    assert client.get(api_route_path(RUN_PATH, run_id=run["id"])).json() == run

    versioned = client.post(
        api_route_path(BOTS_PATH),
        json={**_bot_body(), "definition_version": 2},
    )
    untrusted = client.post(
        api_route_path(BOTS_PATH),
        json={
            **_bot_body(),
            "inputs": {"name": "unsafe", "private_key": "secret"},
        },
    )

    assert versioned.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert untrusted.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert len(state.bots) == 1
    assert len(state.runs) == 1
    assert len(launcher.run_ids) == 1


def test_expired_launch_recovery_and_missing_key_never_enqueue(monkeypatch):
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)
    bot = _create_bot(client)

    async def unavailable(self, bot_id, launch_key):
        raise LaunchAttemptUnavailable

    monkeypatch.setattr(
        _RunStore, "recover_existing_launch", unavailable, raising=False
    )
    path = api_route_path(BOT_RUNS_PATH, bot_id=bot["id"])
    missing_key = client.post(path, headers={IDEMPOTENCY_RECOVERY_HEADER: "true"})
    assert missing_key.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    expired = client.post(
        path,
        headers={
            IDEMPOTENCY_KEY_HEADER: str(uuid4()),
            IDEMPOTENCY_RECOVERY_HEADER: "true",
        },
    )
    assert expired.status_code == status.HTTP_410_GONE
    assert state.runs == {}
    assert launcher.run_ids == []


def test_existing_launch_recovery_bypasses_current_admission_and_never_delivers(
    monkeypatch,
):
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)
    run = _create_run(client)
    key = uuid4()
    launcher.run_ids.clear()

    async def recover(self, bot_id, launch_key):
        assert str(bot_id) == run["bot_id"] and launch_key == key
        return state.runs[run["id"]]

    def reject_fresh_work(*args, **kwargs):
        raise AssertionError("Recovery must not validate or create new work")

    monkeypatch.setattr(_RunStore, "recover_existing_launch", recover, raising=False)
    monkeypatch.setattr(_RunStore, "create_from_bot", reject_fresh_work)
    monkeypatch.setattr(bot_run_routes, "require_catalog_entry", reject_fresh_work)
    monkeypatch.setattr(bot_run_routes, "require_run_graph_contract", reject_fresh_work)
    monkeypatch.setattr(
        PaperRunConfig, "require_subscription_allowance", reject_fresh_work
    )
    response = client.post(
        api_route_path(BOT_RUNS_PATH, bot_id=run["bot_id"]),
        headers={IDEMPOTENCY_KEY_HEADER: str(key), IDEMPOTENCY_RECOVERY_HEADER: "true"},
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json() == run
    assert len(state.runs) == 1
    assert launcher.run_ids == []


def test_catalog_route_and_unknown_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)

    definitions = client.get(api_route_path(BOT_DEFINITIONS_PATH))
    missing = client.post(
        api_route_path(BOTS_PATH),
        json={**_bot_body(), "definition_id": "missing"},
    )

    assert definitions.status_code == status.HTTP_200_OK
    assert WINNER_DEFINITION_ID in {
        definition["definition_id"] for definition in definitions.json()
    }
    node_definition = next(
        definition
        for definition in definitions.json()
        if definition["definition_id"] == NODE_BASED_DEFINITION_ID
    )
    assert node_definition["graph_catalog"]["triggers"][0]["hook_name"] == "on_start"
    assert "version" not in node_definition
    assert set(node_definition["graph_catalog"]) == set(GraphNodeCatalog.model_fields)
    assert all(
        "graph_catalog" not in definition
        for definition in definitions.json()
        if definition["definition_id"] != NODE_BASED_DEFINITION_ID
    )
    assert missing.status_code == status.HTTP_404_NOT_FOUND
    assert state.runs == {}
    assert launcher.run_ids == []


def test_node_graph_saved_bot_persists_exact_snapshot_and_rejects_invalid_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)
    graph = threshold_buy_graph()
    body = {
        "definition_id": NODE_BASED_DEFINITION_ID,
        "inputs": {
            "name": "node-observer",
            "market_slugs": ["example-market"],
        },
        "graph": threshold_buy_graph(),
    }
    saved_bot = client.post(api_route_path(BOTS_PATH), json=body)
    launched = client.post(api_route_path(BOT_RUNS_PATH, bot_id=saved_bot.json()["id"]))
    invalid_graph = {**graph, "schema_version": 1}
    rejected_graph = client.post(
        api_route_path(BOTS_PATH),
        json={**body, "graph": invalid_graph},
    )
    rejected_inputs = client.post(
        api_route_path(BOTS_PATH),
        json={**body, "inputs": {**body["inputs"], "market_slugs": []}},
    )
    missing_template = client.post(
        api_route_path(BOTS_PATH),
        json={"definition_id": NODE_BASED_DEFINITION_ID, "inputs": body["inputs"]},
    )
    forbidden_template = client.post(
        api_route_path(BOTS_PATH),
        json={**_bot_body(), "graph": threshold_buy_graph()},
    )

    assert launched.status_code == status.HTTP_202_ACCEPTED
    assert launched.json()["config"]["graph"] == graph
    assert rejected_graph.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert rejected_inputs.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert missing_template.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert forbidden_template.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert len(state.runs) == 1
    assert launcher.run_ids == [launched.json()["id"]]


def test_saved_bot_rejects_unavailable_additions_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    discovery = client.app.state.market_discovery
    body = {
        "definition_id": NODE_BASED_DEFINITION_ID,
        "inputs": {"name": "selection test", "market_slugs": ["original"]},
        "graph": threshold_buy_graph(),
    }
    bot = client.post(api_route_path(BOTS_PATH), json=body).json()
    discovery.resolve.side_effect = None
    discovery.resolve.return_value = ()

    rejected_create = client.post(api_route_path(BOTS_PATH), json=body)
    rejected_update = client.patch(
        api_route_path(BOT_PATH, bot_id=bot["id"]),
        json={
            "inputs": {"name": "changed", "market_slugs": ["original", "missing"]},
            "graph": threshold_buy_graph(),
        },
    )
    for response in (rejected_create, rejected_update):
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert (
            response.json()["detail"][0]["msg"] == MARKET_SELECTION_UNAVAILABLE_DETAIL
        )
    assert len(state.bots) == 1
    assert (
        client.get(api_route_path(BOT_PATH, bot_id=bot["id"])).json()["config"]
        == bot["config"]
    )


def test_missing_saved_bot_routes_have_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)
    missing_id = uuid4()

    responses = (
        client.get(api_route_path(BOT_PATH, bot_id=missing_id)),
        client.patch(
            api_route_path(BOT_PATH, bot_id=missing_id),
            json={"inputs": {"name": "Missing"}},
        ),
        client.post(api_route_path(BOT_RUNS_PATH, bot_id=missing_id)),
    )

    assert all(
        response.status_code == status.HTTP_404_NOT_FOUND for response in responses
    )
    assert state.bots == {}
    assert state.runs == {}
    assert launcher.run_ids == []


def test_run_launch_rejects_inconsistent_persisted_graph_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)
    graph = threshold_buy_graph()
    graph_bot = client.post(
        api_route_path(BOTS_PATH),
        json={
            "definition_id": NODE_BASED_DEFINITION_ID,
            "inputs": {"name": "graph", "market_slugs": ["market"]},
            "graph": threshold_buy_graph(),
        },
    ).json()
    graph_bot_id = graph_bot["id"]
    state.bots[graph_bot_id].config.graph = None
    plain_bot = _create_bot(client, name="plain")
    plain_bot_id = plain_bot["id"]
    state.bots[plain_bot_id].config.graph = (
        state.bots[graph_bot_id]
        .config.model_validate(
            {**state.bots[graph_bot_id].config.model_dump(mode="json"), "graph": graph}
        )
        .graph
    )

    missing_revision = client.post(api_route_path(BOT_RUNS_PATH, bot_id=graph_bot_id))
    forbidden_revision = client.post(api_route_path(BOT_RUNS_PATH, bot_id=plain_bot_id))

    assert missing_revision.status_code == status.HTTP_409_CONFLICT
    assert forbidden_revision.status_code == status.HTTP_409_CONFLICT
    assert state.runs == {}
    assert launcher.run_ids == []


def test_list_and_detail_derive_latest_event_summaries_without_run_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    run = _create_run(client)
    run_id = run["id"]
    state.events.extend(
        _chart_sample(run_id, index, equity)
        for index, equity in ((1, "101.25"), (2, "102.50"))
    )
    state.events.extend(
        (
            _run_failure(run_id, 3, "ValueError: first failure"),
            _run_failure(run_id, 4, "ConnectionError: stream closed"),
        )
    )

    listed = client.get(api_route_path(RUNS_PATH)).json()[0]
    detailed = client.get(api_route_path(RUN_PATH, run_id=run_id)).json()

    for response in (listed, detailed):
        assert response["latest_equity"] == "102.50"
        assert response["equity_status"] == ValuationStatus.FRESH.value
        assert response["latest_runtime_failure"] == "ConnectionError: stream closed"


def test_queued_and_running_stop_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    redis = _Redis()
    client = _client(monkeypatch, state, redis=redis)
    queued_id = _create_run(client)["id"]
    running_id = _create_run(client, name="running")["id"]
    state.runs[running_id] = state.runs[running_id].model_copy(
        update={"status": RunStatus.RUNNING}
    )
    state.events.append(_chart_sample(running_id, 1, "101.25"))

    queued_first = client.post(api_route_path(RUN_STOP_PATH, run_id=queued_id))
    queued_second = client.post(api_route_path(RUN_STOP_PATH, run_id=queued_id))
    running_first = client.post(api_route_path(RUN_STOP_PATH, run_id=running_id))
    running_second = client.post(api_route_path(RUN_STOP_PATH, run_id=running_id))

    assert queued_first.json()["status"] == RunStatus.STOPPED
    assert queued_second.json()["status"] == RunStatus.STOPPED
    assert running_first.json()["status"] == RunStatus.STOP_REQUESTED
    assert running_first.json()["latest_equity"] == "101.25"
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

    bot = _create_bot(client)
    response = client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]))

    assert response.status_code == status.HTTP_202_ACCEPTED
    run = response.json()
    assert run["status"] == RunStatus.QUEUED
    assert run["failure_detail"] is None
    assert secret not in response.text
    assert state.terminal_event_count == 0
    assert redis.published == []


def test_graph_snapshot_survives_api_stop_and_launch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = threshold_buy_graph()

    def create_graph_bot(client: TestClient, name: str) -> dict[str, object]:
        return client.post(
            api_route_path(BOTS_PATH),
            json={
                "definition_id": NODE_BASED_DEFINITION_ID,
                "inputs": {"name": name, "market_slugs": ["example-market"]},
                "graph": threshold_buy_graph(),
            },
        ).json()

    stopped_client = _client(monkeypatch, _State())
    stopped_bot = create_graph_bot(stopped_client, "stopped graph")
    queued = stopped_client.post(
        api_route_path(BOT_RUNS_PATH, bot_id=stopped_bot["id"])
    ).json()
    stopped = stopped_client.post(
        api_route_path(RUN_STOP_PATH, run_id=queued["id"])
    ).json()

    failed_client = _client(
        monkeypatch,
        _State(),
        launcher=_Launcher(error=RuntimeError("delivery failed")),
    )
    failed_bot = create_graph_bot(failed_client, "failed graph")
    failed = failed_client.post(
        api_route_path(BOT_RUNS_PATH, bot_id=failed_bot["id"])
    ).json()

    for run, expected_status in (
        (stopped, RunStatus.STOPPED),
        (failed, RunStatus.QUEUED),
    ):
        assert run["status"] == expected_status
        assert run["config"]["graph"] == graph


def test_health_requires_postgres_and_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy = _client(monkeypatch, _State())
    assert healthy.get(api_route_path(HEALTH_PATH)).json() == (
        HealthResponse().model_dump()
    )

    unavailable_redis = _client(
        monkeypatch,
        _State(),
        redis=_Redis(ready=False),
    )
    response = unavailable_redis.get(api_route_path(HEALTH_PATH))
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"detail": SERVICE_UNAVAILABLE_DETAIL}

    unavailable_database = _client(
        monkeypatch,
        _State(database_ready=False),
    )
    response = unavailable_database.get(api_route_path(HEALTH_PATH))
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"detail": SERVICE_UNAVAILABLE_DETAIL}


def test_stream_prefers_last_event_id_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    cursors: list[int] = []

    async def stream(self, after_event_id: int):
        cursors.append(after_event_id)
        yield ": complete\n\n"

    client = _client(monkeypatch, state)
    monkeypatch.setattr(events_routes.RunEventStreamer, "stream", stream)
    run_id = _create_run(client)["id"]

    response = client.get(
        api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run_id),
        params={"after_event_id": 1},
        headers={LAST_EVENT_ID_HEADER: "2"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert cursors == [2]

    fallback = client.get(
        api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run_id),
        params={"after_event_id": 3},
    )
    assert fallback.status_code == status.HTTP_200_OK
    assert cursors == [2, 3]


def test_missing_run_event_routes_and_pagination_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, _State())
    missing_id = uuid4()

    assert (
        client.post(api_route_path(RUN_STOP_PATH, run_id=missing_id)).status_code
        == status.HTTP_404_NOT_FOUND
    )
    assert (
        client.get(api_route_path(RUN_EVENTS_PATH, run_id=missing_id)).status_code
        == status.HTTP_404_NOT_FOUND
    )
    assert (
        client.get(
            api_route_path(RUN_EVENTS_STREAM_PATH, run_id=missing_id)
        ).status_code
        == status.HTTP_404_NOT_FOUND
    )
    owned_run_id = _create_run(client)["id"]
    assert (
        client.get(
            api_route_path(RUN_EVENTS_PATH, run_id=owned_run_id),
            params={"before_event_id": FIRST_EVENT_CURSOR - 1},
        ).status_code
        == status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    assert (
        client.get(
            api_route_path(RUN_EVENTS_PATH, run_id=owned_run_id),
            params={"before_event_id": MAX_DURABLE_EVENT_ID + 1},
        ).status_code
        == status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    for invalid_limit in (MIN_EVENT_PAGE_LIMIT - 1, MAX_EVENT_PAGE_LIMIT + 1):
        assert (
            client.get(
                api_route_path(RUN_EVENTS_PATH, run_id=owned_run_id),
                params={"limit": invalid_limit},
            ).status_code
            == status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    assert (
        client.get(
            api_route_path(RUN_EVENTS_STREAM_PATH, run_id=owned_run_id),
            headers={LAST_EVENT_ID_HEADER: str(MAX_DURABLE_EVENT_ID + 1)},
        ).status_code
        == status.HTTP_422_UNPROCESSABLE_CONTENT
    )


def test_event_route_returns_bounded_newest_page_and_older_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    run_id = _create_run(client)["id"]
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

    assert newest.status_code == status.HTTP_200_OK
    assert [event["id"] for event in newest.json()["events"]] == [2, 3]
    assert newest.json()["next_before_event_id"] == 2
    assert [event["id"] for event in older.json()["events"]] == [1]
    assert older.json()["next_before_event_id"] is None


def test_event_route_forwards_selected_view_and_snapshot_cursor(monkeypatch):
    state = _State()
    client = _client(monkeypatch, state)
    run_id = _create_run(client)["id"]
    read_page = AsyncMock(
        return_value=StoredEventPage(
            events=(), next_before_event_id=None, stream_cursor=17
        )
    )
    monkeypatch.setattr(_EventStore, "read_page", read_page)
    for view in EventView:
        response = client.get(
            api_route_path(RUN_EVENTS_PATH, run_id=run_id), params={"view": view.value}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["stream_cursor"] == 17
        assert read_page.call_args.kwargs["view"] is view
    response = client.get(api_route_path(RUN_EVENTS_PATH, run_id=run_id))
    assert response.status_code == status.HTTP_200_OK
    assert read_page.call_args.kwargs["view"] is EventView.ACTIVITY
    assert (
        client.get(
            api_route_path(RUN_EVENTS_PATH, run_id=run_id), params={"view": "invalid"}
        ).status_code
        == status.HTTP_422_UNPROCESSABLE_CONTENT
    )


def test_event_route_enforces_default_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    run_id = _create_run(client)["id"]
    state.events.extend(
        _lifecycle_event(run_id, event_id, RunStatus.RUNNING)
        for event_id in range(1, DEFAULT_EVENT_PAGE_LIMIT + 2)
    )

    page = client.get(api_route_path(RUN_EVENTS_PATH, run_id=run_id)).json()

    assert len(page["events"]) == DEFAULT_EVENT_PAGE_LIMIT
    assert page["events"][0]["id"] == 2
    assert page["events"][-1]["id"] == DEFAULT_EVENT_PAGE_LIMIT + 1
    assert page["next_before_event_id"] == 2


def test_openapi_has_only_v0_routes_and_all_stream_schemas() -> None:
    document = app.openapi()
    encoded = json.dumps(document)

    assert all(path.startswith(API_PREFIX) for path in document["paths"])
    assert "definition_version" not in encoded
    assert "schema_version" not in encoded
    stream_schema = document["paths"][api_route_path(RUN_EVENTS_STREAM_PATH)]["get"][
        "responses"
    ]["200"]["content"][SSE_MEDIA_TYPE]["schema"]
    assert stream_schema == {
        "oneOf": [
            {"$ref": DURABLE_EVENT_SCHEMA_REFERENCE},
            *(
                {"$ref": reference}
                for reference in events_routes.LIVE_EVENT_SCHEMA_REFERENCES
            ),
        ]
    }
    expected = f"{json.dumps(document, indent=2, sort_keys=True)}\n"
    assert OPENAPI_OUTPUT_PATH.read_text() == expected
    assert Path(OPENAPI_OUTPUT_PATH).name == "control-plane.json"


def test_documented_route_inventory_matches_registration() -> None:
    architecture = Path("docs/web-control-plane-architecture.md").read_text()
    http_api = architecture.split("## HTTP API", 1)[1].split("## Frontend", 1)[0]
    documented_routes = set(
        re.findall(r"^- `(GET|POST|PATCH|DELETE) (/[^`?]+)", http_api, re.MULTILINE)
    )

    assert f"`{API_PREFIX}`" in architecture
    assert documented_routes == _openapi_route_methods(app.openapi())


def test_documented_exact_field_inventories_match_contract_owners() -> None:
    architecture = Path("docs/web-control-plane-architecture.md").read_text()

    def documented_fields_after(marker: str) -> tuple[str, ...]:
        field_block = architecture.split(marker, 1)[1].lstrip().split("\n\n", 1)[0]
        return tuple(re.findall(r"^- `([^`]+)`", field_block, re.MULTILINE))

    assert documented_fields_after("`BotDefinitionDescriptor` has exactly:") == tuple(
        BotDefinitionDescriptor.model_fields
    )
    assert documented_fields_after("`BotCreate` has exactly:") == tuple(
        BotCreate.model_fields
    )
    assert documented_fields_after("`BotUpdate` has exactly:") == tuple(
        BotUpdate.model_fields
    )
    assert documented_fields_after(
        "`PaperRunConfig` is the complete saved configuration and run snapshot:"
    ) == tuple(PaperRunConfig.model_fields)
    assert documented_fields_after("The final v0 run row has exactly:") == tuple(
        RunRow.model_fields
    )
    assert documented_fields_after("`bots` has exactly:") == tuple(BotRow.model_fields)


def test_frontend_run_constants_match_backend_contract() -> None:
    assert json.loads(FRONTEND_RUN_CONTRACT_PATH.read_text()) == (
        frontend_run_contract()
    )


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
    discovery = market_discovery()
    monkeypatch.setattr(dependencies_module, "MarketDiscovery", lambda: discovery)
    settings = dependencies_module.StartupSettings(database_url="db", redis_url="redis")
    monkeypatch.setattr(
        dependencies_module.StartupSettings, "from_env", lambda: settings
    )
    monkeypatch.setattr(
        dependencies_module, "create_async_engine", lambda url, **kwargs: engine
    )
    monkeypatch.setattr(
        dependencies_module,
        "async_sessionmaker",
        lambda *args, **kwargs: session_factory,
    )
    monkeypatch.setattr(
        dependencies_module.Redis,
        "from_url",
        lambda url, **kwargs: redis,
    )
    monkeypatch.setattr(dependencies_module, "_default_launcher", lambda: launcher)
    application = create_app()

    with TestClient(application):
        assert application.state.session_factory is session_factory
        assert application.state.redis is redis
        assert application.state.launcher is launcher
        assert application.state.market_discovery is discovery

    assert engine.disposed is True
    assert redis.closed is True
    discovery.close.assert_awaited_once()

    injected_redis = _Redis()
    injected_discovery = market_discovery()
    with TestClient(
        create_app(
            session_factory=object(),
            redis=injected_redis,
            launcher=_Launcher(),
            market_discovery=injected_discovery,
        )
    ):
        pass
    assert injected_redis.closed is False
    injected_discovery.close.assert_not_awaited()


def _client(
    monkeypatch: pytest.MonkeyPatch,
    state: "_State",
    *,
    redis: "_Redis | None" = None,
    launcher: "_Launcher | None" = None,
) -> TestClient:
    monkeypatch.setattr(saved_bot_routes, "BotStore", _BotStore)
    monkeypatch.setattr(bot_run_routes, "BotStore", _BotStore)
    monkeypatch.setattr(bot_run_routes, "RunStore", _RunStore)
    monkeypatch.setattr(runs_routes, "RunStore", _RunStore)
    monkeypatch.setattr(runs_routes, "ApiRunLifecycle", _ApiRunLifecycle)
    monkeypatch.setattr(run_lookup, "RunStore", _RunStore)
    monkeypatch.setattr(events_routes, "EventStore", _EventStore)
    monkeypatch.setattr(runs_routes, "EventStore", _EventStore)
    return TestClient(
        create_app(
            session_factory=_SessionFactory(state),
            redis=redis or _Redis(),
            launcher=launcher or _Launcher(),
            market_discovery=market_discovery(),
        )
    )


def _bot_body(*, name: str = "winner") -> dict[str, object]:
    return {
        "definition_id": WINNER_DEFINITION_ID,
        "inputs": {"name": name, "max_order_size": "2.500"},
    }


def _create_bot(client: TestClient, *, name: str = "winner") -> dict[str, object]:
    response = client.post(api_route_path(BOTS_PATH), json=_bot_body(name=name))
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


def _create_run(client: TestClient, *, name: str = "winner") -> dict[str, object]:
    bot = _create_bot(client, name=name)
    response = client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]))
    assert response.status_code == status.HTTP_202_ACCEPTED
    return response.json()


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


def _chart_sample(run_id: str, event_id: int, equity: str) -> ChartSampleEvent:
    return ChartSampleEvent(
        id=event_id,
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=ChartSamplePayload(
            sampled_at_ms=event_id * 1_000,
            markets=(),
            equity=EquityChartPointPayload(
                value=equity,
                status=ValuationStatus.FRESH,
            ),
        ),
    )


def _run_failure(run_id: str, event_id: int, error: str) -> RunFailureEvent:
    return RunFailureEvent(
        id=event_id,
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=RunFailurePayload(error=error),
    )


class _State:
    def __init__(self, *, database_ready: bool = True) -> None:
        self.database_ready = database_ready
        self.runs: dict[str, RunRead] = {}
        self.bots: dict[str, BotRead] = {}
        self.next_event_id = 1
        self.terminal_event_count = 0
        self.events: list[DurableEvent] = []


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

    async def rollback(self) -> None:
        return None


class _BotStore:
    def __init__(self, session: _Session, owner_user_id) -> None:
        assert owner_user_id == TEST_USER_ID
        self.state = session.state

    async def create(self, *, definition_id, config) -> BotRead:
        now = datetime.now(UTC)
        bot_id = uuid4()
        bot = BotRead(
            id=bot_id,
            definition_id=definition_id,
            config=config,
            created_at=now,
            updated_at=now,
        )
        self.state.bots[str(bot.id)] = bot
        return bot

    async def read(self, bot_id, *, lock=False) -> BotRead | None:
        return self.state.bots.get(str(bot_id))

    async def list(self) -> tuple[BotRead, ...]:
        return tuple(
            sorted(
                self.state.bots.values(),
                key=lambda bot: (bot.updated_at, bot.id),
                reverse=True,
            )
        )

    async def update_config(self, bot_id, config) -> BotRead | None:
        bot = self.state.bots.get(str(bot_id))
        if bot is None:
            return None
        updated = bot.model_copy(
            update={"config": config, "updated_at": datetime.now(UTC)}
        )
        self.state.bots[str(bot_id)] = updated
        return updated


class _RunStore:
    def __init__(self, session: _Session, owner_user_id=None) -> None:
        self.state = session.state

    async def create_from_bot(self, bot: BotRead, *, launch_key=None) -> RunRead:
        run = RunRead(
            id=uuid4(),
            bot_id=bot.id,
            definition_id=bot.definition_id,
            config=bot.config.model_copy(deep=True),
            status=RunStatus.QUEUED,
            created_at=datetime.now(UTC),
        )
        self.state.runs[str(run.id)] = run
        return run

    async def read_owned(self, run_id, owner_user_id):
        assert owner_user_id == TEST_USER_ID
        return await self.read(run_id)

    async def list_owned(self, owner_user_id):
        assert owner_user_id == TEST_USER_ID
        return await self.list()

    async def read(self, run_id) -> RunRead | None:
        return self.state.runs.get(str(run_id))

    async def list(self) -> tuple[RunRead, ...]:
        return tuple(
            sorted(
                self.state.runs.values(),
                key=lambda run: (run.created_at, run.id),
                reverse=True,
            )
        )


class _EventStore:
    def __init__(self, session: _Session, owner_user_id=None) -> None:
        self.state = session.state

    async def read_page(self, run_id, *, before_event_id, limit, view):
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
        ascending_page = tuple(reversed(page))
        return StoredEventPage(
            events=ascending_page,
            stream_cursor=max(
                (event.id for event in self.state.events if event.run_id == run_id),
                default=FIRST_EVENT_CURSOR,
            ),
            next_before_event_id=next_event_page_cursor(
                tuple(event.id for event in ascending_page if event.id is not None),
                has_more=has_more,
            ),
        )

    async def latest_chart_samples(self, run_ids):
        result = {}
        for event in self.state.events:
            if isinstance(event, ChartSampleEvent) and event.run_id in run_ids:
                result[event.run_id] = event
        return result

    async def latest_run_failures(self, run_ids):
        result = {}
        for event in self.state.events:
            if isinstance(event, RunFailureEvent) and event.run_id in run_ids:
                result[event.run_id] = event
        return result


class _ApiRunLifecycle:
    def __init__(self, session: _Session, owner_user_id=None) -> None:
        self.state = session.state

    async def request_stop(self, run_id, *, now):
        key = str(run_id)
        run = self.state.runs.get(key)
        if run is None:
            return None
        event_id = None
        if run.status is RunStatus.QUEUED:
            run = run.model_copy(update={"status": RunStatus.STOPPED, "ended_at": now})
            event_id = self._terminal_event_id()
        elif run.status in {RunStatus.STARTING, RunStatus.RUNNING}:
            run = run.model_copy(update={"status": RunStatus.STOP_REQUESTED})
        self.state.runs[key] = run
        return run, event_id

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


def test_atomic_bot_save_rejects_invalid_graph_without_changing_settings(monkeypatch):
    client = _client(monkeypatch, _State())
    body = {
        "definition_id": NODE_BASED_DEFINITION_ID,
        "inputs": {"name": "before", "market_slugs": ["market"]},
        "graph": threshold_buy_graph(),
    }
    bot = client.post(api_route_path(BOTS_PATH), json=body).json()
    first = client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"])).json()
    path = api_route_path(BOT_PATH, bot_id=bot["id"])
    invalid = client.patch(
        path,
        json={
            "inputs": {**body["inputs"], "name": "after"},
            "graph": {"nodes": [], "edges": []},
        },
    )
    assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert client.get(path).json()["config"] == bot["config"]
    edited_graph = threshold_buy_graph()
    edited_graph["nodes"][1]["position"]["x"] += 1
    saved = client.patch(
        path,
        json={"inputs": {**body["inputs"], "name": "after"}, "graph": edited_graph},
    )
    assert saved.status_code == status.HTTP_200_OK
    assert saved.json()["config"]["name"] == "after"
    assert saved.json()["config"]["graph"] == edited_graph
    assert (
        client.get(api_route_path(RUN_PATH, run_id=first["id"])).json()["config"]
        == bot["config"]
    )
    second = client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"])).json()
    assert second["config"] == saved.json()["config"]


@pytest.mark.parametrize("view", [None, EventView.DIAGNOSTICS])
def test_stream_forwards_event_view_and_defaults_to_activity(monkeypatch, view):
    observed = []

    async def stream(self, after_event_id):
        observed.append(self._replay._view)
        yield ": complete\n\n"

    client = _client(monkeypatch, _State())
    monkeypatch.setattr(events_routes.RunEventStreamer, "stream", stream)
    run_id = _create_run(client)["id"]
    response = client.get(
        api_route_path(RUN_EVENTS_STREAM_PATH, run_id=run_id),
        params={} if view is None else {"view": view},
    )
    assert response.status_code == status.HTTP_200_OK
    assert observed == [EventView.ACTIVITY if view is None else view]
