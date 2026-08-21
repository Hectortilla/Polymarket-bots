from datetime import UTC
from uuid import uuid4

from polybot.cli.observability.events import RuntimeFailed, RuntimeStateChanged
from polybot.cli.observability.states import RuntimeState
from polybot_control_plane.events.contracts import EventKind
from polybot_control_plane.events.projection import project_event


def test_runtime_projection_keeps_durable_kind_and_payload() -> None:
    run_id = uuid4()
    event = project_event(run_id, RuntimeStateChanged(RuntimeState.RUNNING, 12.5))

    assert event is not None
    assert event.run_id == run_id
    assert event.kind is EventKind.RUN_LIFECYCLE
    assert event.payload["state"] == RuntimeState.RUNNING.value


def test_runtime_failure_projects_to_failure_event() -> None:
    event = project_event(uuid4(), RuntimeFailed("secret", 12.5))

    assert event is not None
    assert event.kind is EventKind.RUN_FAILURE
    assert event.payload["error"] == "secret"
    assert event.occurred_at.tzinfo is UTC
