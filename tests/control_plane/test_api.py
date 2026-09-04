from datetime import UTC, datetime
import json
from pathlib import Path
import re
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError

import polybot_control_plane.api.dependencies as dependencies_module
import polybot_control_plane.api.openapi as openapi_module
import polybot_control_plane.api.routes.events as events_routes
import polybot_control_plane.api.routes.bots.run_launch as bot_run_routes
import polybot_control_plane.api.routes.bots.saved_bot as saved_bot_routes
import polybot_control_plane.api.routes.bots.validation as bot_validation
import polybot_control_plane.api.routes.graph_templates as graph_template_routes
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
    BOTS_PATH,
    BOT_GRAPH_REVISION_PATH,
    BOT_GRAPH_REVISIONS_PATH,
    BOT_PATH,
    BOT_RUNS_PATH,
    GRAPH_TEMPLATE_PATH,
    GRAPH_TEMPLATES_PATH,
    HEALTH_PATH,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    RUNS_PATH,
    api_route_path,
)
from polybot_control_plane.bots.revisions import (
    FIRST_GRAPH_REVISION_NUMBER,
    next_graph_revision_number,
)
from polybot_control_plane.api.routes.bots.run_launch import RUN_LAUNCH_FAILURE_REASON
from polybot_control_plane.api.openapi import OPENAPI_OUTPUT_PATH
from polybot_control_plane.catalog.definitions import (
    NODE_BASED_DEFINITION_ID,
    WINNER_DEFINITION_ID,
)
from polybot_control_plane.catalog.contracts import BotDefinitionDescriptor
from polybot_control_plane.catalog.graphs.catalog import GraphNodeCatalog
from polybot_control_plane.bots.contracts import BotGraphRevisionRead, BotRead
from polybot_control_plane.bots.contracts import BotCreate, BotUpdate
from polybot_control_plane.bots.models import BotGraphRevisionRow, BotRow
from polybot_control_plane.graph_templates.contracts import GraphTemplateRead
from polybot_control_plane.graph_templates.models import GraphTemplateRow
from polybot_control_plane.events.contracts import (
    ChartSampleEvent,
    ChartSamplePayload,
    DurableEvent,
    RunFailureEvent,
    RunFailurePayload,
    RunLifecycleEvent,
    RunStatusPayload,
)
from polybot_control_plane.events.contracts.payloads import EquityChartPointPayload
from polybot_control_plane.events.ids import (
    FIRST_EVENT_CURSOR,
    MAX_DURABLE_EVENT_ID,
)
from polybot_control_plane.events.pagination import (
    DEFAULT_EVENT_PAGE_LIMIT,
    MAX_EVENT_PAGE_LIMIT,
    MIN_EVENT_PAGE_LIMIT,
    next_event_page_cursor,
)
from polybot_control_plane.events.store import StoredEventPage
from polybot_control_plane.runs.contracts import PaperRunConfig, RunRead
from polybot_control_plane.runs.models import RunRow
from polybot_control_plane.runs.status import RunStatus
from polybot.performance.contracts.valuation_status import ValuationStatus
from control_plane.graph_fixtures import threshold_buy_graph
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

    assert launched.status_code == 202
    run = launched.json()
    assert run["definition_id"] == WINNER_DEFINITION_ID
    assert run["bot_id"] == bot["id"]
    assert "definition_version" not in run
    assert run["config"]["max_order_size"] == "2.500"
    assert "graph" not in run["config"]
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

    assert versioned.status_code == 422
    assert untrusted.status_code == 422
    assert len(state.bots) == 1
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
        api_route_path(BOTS_PATH),
        json={**_bot_body(), "definition_id": "missing"},
    )

    assert definitions.status_code == 200
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
    assert missing.status_code == 404
    assert state.runs == {}
    assert launcher.run_ids == []


def test_node_graph_saved_bot_persists_exact_snapshot_and_rejects_invalid_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)
    graph = threshold_buy_graph()
    template = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": "Threshold", "graph": graph},
    )
    body = {
        "definition_id": NODE_BASED_DEFINITION_ID,
        "inputs": {
            "name": "node-observer",
            "market_slugs": ["example-market"],
        },
        "graph_template_id": template.json()["id"],
    }
    saved_bot = client.post(api_route_path(BOTS_PATH), json=body)
    launched = client.post(
        api_route_path(BOT_RUNS_PATH, bot_id=saved_bot.json()["id"])
    )
    invalid_graph = {**graph, "schema_version": 1}
    rejected_graph = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": "Invalid", "graph": invalid_graph},
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
        json={**_bot_body(), "graph_template_id": template.json()["id"]},
    )

    assert launched.status_code == 202
    assert launched.json()["graph"] == graph
    assert "graph" not in launched.json()["config"]
    assert launched.json()["graph_revision"] == FIRST_GRAPH_REVISION_NUMBER
    assert rejected_graph.status_code == 422
    assert rejected_inputs.status_code == 422
    assert missing_template.status_code == 422
    assert forbidden_template.status_code == 422
    assert len(state.runs) == 1
    assert launcher.run_ids == [launched.json()["id"]]


def test_template_and_bot_graph_edits_are_isolated_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, _State())
    original_graph = threshold_buy_graph()
    changed_graph = threshold_buy_graph()
    changed_graph["nodes"][1]["data"]["value"] = "0.6000"
    bot_graph = threshold_buy_graph()
    bot_graph["nodes"][1]["data"]["value"] = "0.7000"
    template = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": "Reusable", "graph": original_graph},
    ).json()
    bot = client.post(
        api_route_path(BOTS_PATH),
        json={
            "definition_id": NODE_BASED_DEFINITION_ID,
            "inputs": {"name": "isolated", "market_slugs": ["market"]},
            "graph_template_id": template["id"],
        },
    ).json()

    updated_template = client.patch(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=template["id"]),
        json={"graph": changed_graph},
    ).json()
    unchanged_bot = client.get(
        api_route_path(BOT_PATH, bot_id=bot["id"])
    ).json()
    revision_two = client.post(
        api_route_path(BOT_GRAPH_REVISIONS_PATH, bot_id=bot["id"]),
        json={"graph": bot_graph},
    ).json()
    unchanged_template = client.get(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=template["id"])
    ).json()

    assert updated_template["graph"] == changed_graph
    assert unchanged_bot["latest_graph_revision"]["graph"] == original_graph
    assert revision_two["latest_graph_revision"]["revision"] == (
        FIRST_GRAPH_REVISION_NUMBER + 1
    )
    assert revision_two["latest_graph_revision"]["graph"] == bot_graph
    assert unchanged_template["graph"] == changed_graph


def test_template_and_saved_bot_crud_preserve_revision_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    graph = threshold_buy_graph()
    template = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": "  Reusable graph  ", "graph": graph},
    ).json()
    bot = client.post(
        api_route_path(BOTS_PATH),
        json={
            "definition_id": NODE_BASED_DEFINITION_ID,
            "inputs": {"name": "before", "market_slugs": ["market"]},
            "graph_template_id": template["id"],
        },
    ).json()
    revision = bot["latest_graph_revision"]

    updated_bot = client.patch(
        api_route_path(BOT_PATH, bot_id=bot["id"]),
        json={"inputs": {"name": "after", "market_slugs": ["market"]}},
    )
    read_revision = client.get(
        api_route_path(
            BOT_GRAPH_REVISION_PATH,
            bot_id=bot["id"],
            revision_id=revision["id"],
        )
    )
    wrong_owner = client.get(
        api_route_path(
            BOT_GRAPH_REVISION_PATH,
            bot_id=uuid4(),
            revision_id=revision["id"],
        )
    )
    non_graph_bot = _create_bot(client, name="plain")
    forbidden_revision = client.post(
        api_route_path(BOT_GRAPH_REVISIONS_PATH, bot_id=non_graph_bot["id"]),
        json={"graph": graph},
    )
    bots_before_missing_template = len(state.bots)
    missing_template = client.post(
        api_route_path(BOTS_PATH),
        json={
            "definition_id": NODE_BASED_DEFINITION_ID,
            "inputs": {"name": "missing", "market_slugs": ["market"]},
            "graph_template_id": str(uuid4()),
        },
    )

    assert template["name"] == "Reusable graph"
    assert client.get(api_route_path(GRAPH_TEMPLATES_PATH)).json() == [template]
    assert client.get(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=template["id"])
    ).json() == template
    assert updated_bot.status_code == 200
    assert updated_bot.json()["config"]["name"] == "after"
    assert updated_bot.json()["latest_graph_revision"] == revision
    assert {
        saved_bot["id"]
        for saved_bot in client.get(api_route_path(BOTS_PATH)).json()
    } == {
        bot["id"],
        non_graph_bot["id"],
    }
    assert read_revision.status_code == 200
    assert read_revision.json() == revision
    assert wrong_owner.status_code == 404
    assert forbidden_revision.status_code == 422
    assert missing_template.status_code == 404
    assert len(state.bots) == bots_before_missing_template


def test_graph_template_conflicts_and_missing_writes_preserve_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    client = _client(monkeypatch, state)
    graph = threshold_buy_graph()
    first = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": "Reusable", "graph": graph},
    ).json()
    second = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": "Other", "graph": graph},
    ).json()

    duplicate = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": first["name"], "graph": graph},
    )
    conflicting_rename = client.patch(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=second["id"]),
        json={"name": first["name"]},
    )
    missing_id = uuid4()

    assert duplicate.status_code == 409
    assert conflicting_rename.status_code == 409
    assert client.get(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=missing_id)
    ).status_code == 404
    assert client.patch(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=missing_id),
        json={"name": "Missing"},
    ).status_code == 404
    assert client.patch(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=first["id"]),
        json={},
    ).status_code == 422
    assert client.get(
        api_route_path(GRAPH_TEMPLATE_PATH, template_id=second["id"])
    ).json()["name"] == "Other"


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
        client.post(
            api_route_path(BOT_GRAPH_REVISIONS_PATH, bot_id=missing_id),
            json={"graph": threshold_buy_graph()},
        ),
        client.post(api_route_path(BOT_RUNS_PATH, bot_id=missing_id)),
    )

    assert all(response.status_code == 404 for response in responses)
    assert state.bots == {}
    assert state.revisions == {}
    assert state.runs == {}
    assert launcher.run_ids == []


def test_run_launch_rejects_inconsistent_persisted_graph_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _State()
    launcher = _Launcher()
    client = _client(monkeypatch, state, launcher=launcher)
    graph = threshold_buy_graph()
    template = client.post(
        api_route_path(GRAPH_TEMPLATES_PATH),
        json={"name": "Graph", "graph": graph},
    ).json()
    graph_bot = client.post(
        api_route_path(BOTS_PATH),
        json={
            "definition_id": NODE_BASED_DEFINITION_ID,
            "inputs": {"name": "graph", "market_slugs": ["market"]},
            "graph_template_id": template["id"],
        },
    ).json()
    graph_bot_id = graph_bot["id"]
    state.bots[graph_bot_id] = state.bots[graph_bot_id].model_copy(
        update={"latest_graph_revision": None}
    )
    plain_bot = _create_bot(client, name="plain")
    plain_bot_id = plain_bot["id"]
    state.bots[plain_bot_id] = state.bots[plain_bot_id].model_copy(
        update={
            "latest_graph_revision": BotGraphRevisionRead(
                id=uuid4(),
                bot_id=state.bots[plain_bot_id].id,
                revision=FIRST_GRAPH_REVISION_NUMBER,
                graph=graph,
                created_at=datetime.now(UTC),
            )
        }
    )

    missing_revision = client.post(
        api_route_path(BOT_RUNS_PATH, bot_id=graph_bot_id)
    )
    forbidden_revision = client.post(
        api_route_path(BOT_RUNS_PATH, bot_id=plain_bot_id)
    )

    assert missing_revision.status_code == 409
    assert forbidden_revision.status_code == 409
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

    assert response.status_code == 202
    run = response.json()
    assert run["status"] == RunStatus.FAILED
    assert run["failure_detail"] == f"RuntimeError: {RUN_LAUNCH_FAILURE_REASON}"
    assert secret not in run["failure_detail"]
    assert state.terminal_event_count == 1
    assert len(redis.published) == 1


def test_graph_snapshot_survives_api_stop_and_launch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = threshold_buy_graph()

    def create_graph_bot(client: TestClient, name: str) -> dict[str, object]:
        template = client.post(
            api_route_path(GRAPH_TEMPLATES_PATH),
            json={"name": f"{name} template", "graph": graph},
        ).json()
        return client.post(
            api_route_path(BOTS_PATH),
            json={
                "definition_id": NODE_BASED_DEFINITION_ID,
                "inputs": {"name": name, "market_slugs": ["example-market"]},
                "graph_template_id": template["id"],
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

    for run, status in (
        (stopped, RunStatus.STOPPED),
        (failed, RunStatus.FAILED),
    ):
        assert run["status"] == status
        assert run["graph_revision"] == FIRST_GRAPH_REVISION_NUMBER
        assert run["graph"] == graph


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
            params={"before_event_id": FIRST_EVENT_CURSOR - 1},
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
    for invalid_limit in (MIN_EVENT_PAGE_LIMIT - 1, MAX_EVENT_PAGE_LIMIT + 1):
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
    stream_schema = document["paths"][
        api_route_path(RUN_EVENTS_STREAM_PATH)
    ]["get"]["responses"]["200"]["content"][SSE_MEDIA_TYPE]["schema"]
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
        re.findall(r"^- `(GET|POST|PATCH) (/[^`?]+)", http_api, re.MULTILINE)
    )

    assert f"`{API_PREFIX}`" in architecture
    assert documented_routes == _openapi_route_methods(app.openapi())


def test_documented_exact_field_inventories_match_contract_owners() -> None:
    architecture = Path("docs/web-control-plane-architecture.md").read_text()

    def documented_fields_after(marker: str) -> tuple[str, ...]:
        field_block = (
            architecture.split(marker, 1)[1].lstrip().split("\n\n", 1)[0]
        )
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
        "`PaperRunConfig` is the complete persisted paper snapshot and contains only "
        "the\nnon-sensitive `BotConfig` inputs used by web runs:"
    ) == tuple(PaperRunConfig.model_fields)
    assert documented_fields_after("The final v0 run row has exactly:") == tuple(
        RunRow.model_fields
    )
    assert documented_fields_after("`graph_templates` has exactly:") == tuple(
        GraphTemplateRow.model_fields
    )
    assert documented_fields_after("`bots` has exactly:") == tuple(
        BotRow.model_fields
    )
    assert documented_fields_after("`bot_graph_revisions` has exactly:") == tuple(
        BotGraphRevisionRow.model_fields
    )


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
    monkeypatch.setattr(saved_bot_routes, "BotStore", _BotStore)
    monkeypatch.setattr(bot_validation, "GraphTemplateStore", _GraphTemplateStore)
    monkeypatch.setattr(bot_run_routes, "BotStore", _BotStore)
    monkeypatch.setattr(bot_run_routes, "RunStore", _RunStore)
    monkeypatch.setattr(bot_run_routes, "ApiRunLifecycle", _ApiRunLifecycle)
    monkeypatch.setattr(
        graph_template_routes,
        "GraphTemplateStore",
        _GraphTemplateStore,
    )
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
        )
    )


def _bot_body(*, name: str = "winner") -> dict[str, object]:
    return {
        "definition_id": WINNER_DEFINITION_ID,
        "inputs": {"name": name, "max_order_size": "2.500"},
    }


def _create_bot(client: TestClient, *, name: str = "winner") -> dict[str, object]:
    response = client.post(api_route_path(BOTS_PATH), json=_bot_body(name=name))
    assert response.status_code == 201
    return response.json()


def _create_run(client: TestClient, *, name: str = "winner") -> dict[str, object]:
    bot = _create_bot(client, name=name)
    response = client.post(api_route_path(BOT_RUNS_PATH, bot_id=bot["id"]))
    assert response.status_code == 202
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
        self.templates: dict[str, GraphTemplateRead] = {}
        self.revisions: dict[str, BotGraphRevisionRead] = {}
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


class _GraphTemplateStore:
    def __init__(self, session: _Session) -> None:
        self.state = session.state

    async def create(self, request) -> GraphTemplateRead:
        self._raise_if_name_conflicts(request.name)
        now = datetime.now(UTC)
        template = GraphTemplateRead(
            id=uuid4(),
            name=request.name,
            graph=request.graph,
            created_at=now,
            updated_at=now,
        )
        self.state.templates[str(template.id)] = template
        return template

    async def read(self, template_id) -> GraphTemplateRead | None:
        return self.state.templates.get(str(template_id))

    async def list(self) -> tuple[GraphTemplateRead, ...]:
        return tuple(
            sorted(
                self.state.templates.values(),
                key=lambda template: (template.name, str(template.id)),
            )
        )

    async def update(self, template_id, request) -> GraphTemplateRead | None:
        existing = self.state.templates.get(str(template_id))
        if existing is None:
            return None
        if request.name is not None:
            self._raise_if_name_conflicts(request.name, excluding=template_id)
        updated = existing.model_copy(
            update={
                "name": request.name or existing.name,
                "graph": request.graph or existing.graph,
                "updated_at": datetime.now(UTC),
            }
        )
        self.state.templates[str(template_id)] = updated
        return updated

    def _raise_if_name_conflicts(self, name, *, excluding=None) -> None:
        if any(
            template.name == name and template.id != excluding
            for template in self.state.templates.values()
        ):
            raise IntegrityError("duplicate graph template name", {}, Exception())


class _BotStore:
    def __init__(self, session: _Session) -> None:
        self.state = session.state

    async def create(self, *, definition_id, config, graph) -> BotRead:
        now = datetime.now(UTC)
        bot_id = uuid4()
        revision = None
        if graph is not None:
            revision = BotGraphRevisionRead(
                id=uuid4(),
                bot_id=bot_id,
                revision=FIRST_GRAPH_REVISION_NUMBER,
                graph=graph,
                created_at=now,
            )
            self.state.revisions[str(revision.id)] = revision
        bot = BotRead(
            id=bot_id,
            definition_id=definition_id,
            config=config,
            latest_graph_revision=revision,
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

    async def append_revision(self, bot_id, graph) -> BotRead | None:
        bot = self.state.bots.get(str(bot_id))
        if bot is None:
            return None
        revision = BotGraphRevisionRead(
            id=uuid4(),
            bot_id=bot.id,
            revision=next_graph_revision_number(
                None
                if bot.latest_graph_revision is None
                else bot.latest_graph_revision.revision
            ),
            graph=graph,
            created_at=datetime.now(UTC),
        )
        self.state.revisions[str(revision.id)] = revision
        updated = bot.model_copy(
            update={
                "latest_graph_revision": revision,
                "updated_at": revision.created_at,
            }
        )
        self.state.bots[str(bot_id)] = updated
        return updated

    async def read_revision(self, bot_id, revision_id) -> BotGraphRevisionRead | None:
        revision = self.state.revisions.get(str(revision_id))
        return revision if revision is not None and revision.bot_id == bot_id else None


class _RunStore:
    def __init__(self, session: _Session) -> None:
        self.state = session.state

    async def create_from_bot(self, bot: BotRead) -> RunRead:
        revision = bot.latest_graph_revision
        run = RunRead(
            id=uuid4(),
            bot_id=bot.id,
            definition_id=bot.definition_id,
            config=bot.config,
            bot_graph_revision_id=revision.id if revision else None,
            graph_revision=revision.revision if revision else None,
            graph=revision.graph if revision else None,
            status=RunStatus.QUEUED,
            created_at=datetime.now(UTC),
        )
        self.state.runs[str(run.id)] = run
        return run

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
        ascending_page = tuple(reversed(page))
        return StoredEventPage(
            events=ascending_page,
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
