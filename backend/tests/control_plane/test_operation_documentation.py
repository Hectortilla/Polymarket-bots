"""Runbook and Compose contracts derive from operation policy owners."""

import re
from pathlib import Path

from api.deployment.settings import (
    DEPLOYMENT_STORAGE_PROBE_PATH,
    LEASE_SECONDS_ENV,
    STORAGE_PROBE_PATH_ENV,
)
from api.events.health.policy import FEED_TTL_SECONDS
from api.execution.policy import RUNTIME_CLEANUP_SECONDS
from api.limits.errors import ResourceLimitCode
from api.limits.http import RESOURCE_STATUS
from api.operations.alerts import ALERT_DEFINITIONS
from api.operations.alerts.policy import ALERT_OWNER
from api.operations.commands import ALL_OPERATION_COMMANDS
from api.operations.monitor import MONITOR_INTERVAL_SECONDS
from api.operations.observations.sink import MAX_QUEUED_OPERATION_RECORDS
from api.operations.telemetry.counters import METRIC_TTL_SECONDS, METRIC_WINDOW_SECONDS
from api.operations.telemetry.presence_policy import (
    PRESENCE_HEARTBEAT_SECONDS,
    PRESENCE_TTL_SECONDS,
)
from api.runs.lease_policy import DEFAULT_HEARTBEAT_SECONDS

RUNBOOK_PATH = Path("docs/beta-operations.md")


def alert_policy_table():
    lines = [
        "| Alert | Condition | Threshold | Unit / interpretation | Response |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for definition in ALERT_DEFINITIONS.values():
        lines.append(
            f"| `{definition.code}` | {definition.direction} | {definition.threshold:g} | {definition.unit} | {definition.response} |"
        )
    return "\n".join(lines)


def cadence_policy_table():
    entries = {
        "Monitor interval seconds": MONITOR_INTERVAL_SECONDS,
        "Process heartbeat seconds": PRESENCE_HEARTBEAT_SECONDS,
        "Process presence TTL seconds": PRESENCE_TTL_SECONDS,
        "Feed observation TTL seconds": FEED_TTL_SECONDS,
        "Counter window seconds (current plus previous)": METRIC_WINDOW_SECONDS,
        "Counter TTL seconds": METRIC_TTL_SECONDS,
        "Maximum queued log records": MAX_QUEUED_OPERATION_RECORDS,
    }
    return "\n".join(
        [
            "| Policy | Value |",
            "| --- | ---: |",
            *(f"| {name} | {value:g} |" for name, value in entries.items()),
        ]
    )


def test_operator_runbook_matches_policy_and_complete_command_vocabulary():
    text = RUNBOOK_PATH.read_text()
    for marker, expected in (
        ("operational-alerts", alert_policy_table()),
        ("operational-cadence", cadence_policy_table()),
    ):
        actual = (
            text.split(f"<!-- {marker}:start -->", 1)[1]
            .split(f"<!-- {marker}:end -->", 1)[0]
            .strip()
        )
        assert actual == expected
    assert ALERT_OWNER in text
    for command in ALL_OPERATION_COMMANDS:
        assert f"python -m api.operations {command}" in text


def test_compose_storage_probe_matches_validated_configuration():
    compose = Path("deploy/compose.yaml").read_text()
    assert (
        f"{STORAGE_PROBE_PATH_ENV}: &storage_probe_path {DEPLOYMENT_STORAGE_PROBE_PATH}"
        in compose
    )
    assert "target: *storage_probe_path\n        read_only: true" in compose


def test_runbook_arity_and_runtime_defaults_match_implementation():
    runbook = RUNBOOK_PATH.read_text()
    commands = {str(command): command for command in ALL_OPERATION_COMMANDS}
    for line in runbook.splitlines():
        if line.startswith("uv run --env-file .env python -m api.operations "):
            arguments = line.split("api.operations ", 1)[1].split()
            assert len(arguments) == (
                2 if commands[arguments[0]].requires_target else 1
            )
    timing = f"Default worker cleanup budget: heartbeat {DEFAULT_HEARTBEAT_SECONDS:g} seconds plus cleanup {RUNTIME_CLEANUP_SECONDS:g} seconds."
    assert timing in runbook
    assert timing in Path("docs/web-control-plane-spec.md").read_text()
    assert "The table shows default thresholds" in runbook
    assert LEASE_SECONDS_ENV in runbook
    architecture = Path("docs/web-control-plane-architecture.md").read_text()
    assert (
        f"`{ResourceLimitCode.INCIDENT_PAUSED}`\n({RESOURCE_STATUS[ResourceLimitCode.INCIDENT_PAUSED]}) and `{ResourceLimitCode.ACCOUNT_SUSPENDED}` ({RESOURCE_STATUS[ResourceLimitCode.ACCOUNT_SUSPENDED]})"
        in architecture
    )
    compose = Path("deploy/compose.yaml").read_text()
    rotation = re.search(r"max-size: (\d+)m, max-file: '(\d+)'", compose)
    assert rotation is not None
    assert (
        f"Logs rotate at {rotation[1]} MiB with {rotation[2]} files per service."
        in runbook
    )
