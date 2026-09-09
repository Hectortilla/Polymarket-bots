"""Keep declarative process names and shutdown bounds aligned with their owners."""

from pathlib import Path

from api import io_policy
from api.deployment.services import APPLICATION_SERVICES, DeploymentService
from api.execution import policy as execution_policy
from api.execution.policy import RECOVERY_STOP_GRACE_SECONDS, WORKER_STOP_GRACE_SECONDS
from api.execution.recovery import policy as recovery_policy
from api.runs import lease_policy


def test_compose_recovery_service_and_shutdown_bounds_match_policy():
    production = Path("deploy/compose.yaml").read_text()
    acceptance = Path("deploy/acceptance.compose.yaml").read_text()
    for service in APPLICATION_SERVICES:
        assert f"\n  {service}:\n" in production
    recovery_command = f"    command: [{DeploymentService.RECOVERY}]"
    assert recovery_command in production and recovery_command in acceptance
    recovery_block = production.split(f"\n  {DeploymentService.RECOVERY}:\n", 1)[
        1
    ].split("\n  migrate:", 1)[0]
    worker_block = production.split(f"\n  {DeploymentService.WORKER}:\n", 1)[1].split(
        f"\n  {DeploymentService.RECOVERY}:", 1
    )[0]
    assert f"stop_grace_period: {RECOVERY_STOP_GRACE_SECONDS}s" in recovery_block
    assert f"stop_grace_period: {WORKER_STOP_GRACE_SECONDS}s" in worker_block


def test_reliability_runbook_and_policy_table_match_code():
    architecture = Path("docs/web-control-plane-architecture.md").read_text()
    table = (
        architecture.split("<!-- reliability-policy:start -->", 1)[1]
        .split("<!-- reliability-policy:end -->", 1)[0]
        .strip()
    )
    entries = (
        ("Worker heartbeat", lease_policy, "DEFAULT_HEARTBEAT_SECONDS"),
        ("Worker lease", lease_policy, "DEFAULT_LEASE_SECONDS"),
        ("Recovery retry", recovery_policy, "DELIVERY_RETRY_SECONDS"),
        ("Dependency operation", io_policy, "DEPENDENCY_TIMEOUT_SECONDS"),
        ("Taskiq read block", execution_policy, "TASKIQ_READ_BLOCK_SECONDS"),
        ("Taskiq job drain", execution_policy, "TASKIQ_DRAIN_SECONDS"),
        ("Runtime cleanup", execution_policy, "RUNTIME_CLEANUP_SECONDS"),
        ("Taskiq shutdown", execution_policy, "TASKIQ_SHUTDOWN_SECONDS"),
        ("Worker process stop", execution_policy, "WORKER_STOP_GRACE_SECONDS"),
        ("Recovery process stop", execution_policy, "RECOVERY_STOP_GRACE_SECONDS"),
    )
    expected = ["| Policy | Default seconds | Code owner |", "| --- | ---: | --- |"]
    for label, module, attribute in entries:
        expected.append(
            f"| {label} | {getattr(module, attribute):g} | `{module.__name__}.{attribute}` |"
        )
    assert table == "\n".join(expected)
    runbook = Path("docs/beta-deployment.md").read_text()
    procedure = runbook.split("## Release and rollback", 1)[1].split("For rollback", 1)[
        0
    ]
    for service in APPLICATION_SERVICES[1:]:
        assert f"`{service}`" in procedure
    plan = Path("docs/implementation-plan.md").read_text()
    assert "A launcher failure preserves the committed queued run" in plan
    assert "A launcher failure leaves a visible durable failed run" not in plan


def test_local_worker_command_uses_the_configured_drain_bound():
    readme = Path("README.md").read_text()
    assert f"--wait-tasks-timeout {execution_policy.TASKIQ_DRAIN_SECONDS:g}" in readme
    assert f"--shutdown-timeout {execution_policy.TASKIQ_SHUTDOWN_SECONDS:g}" in readme
