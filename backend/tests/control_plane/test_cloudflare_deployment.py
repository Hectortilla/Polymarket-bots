"""Public ingress opt-in, secret handling and independent management identity."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from api.auth.config import AUTH_ORIGIN_ENV
from jinja2 import Environment

from control_plane.test_deployment_contracts import inventory_values, render_template
from control_plane.test_host_monitoring import host_config, serve_config
from scripts.deployment.bootstrap_inputs import BootstrapInputs
from scripts.deployment.dotenv import parse_values
from scripts.deployment.ingress import IngressMode, IngressSettings
from scripts.deployment.inventory import DeploymentInventory
from scripts.deployment.paths import CLOUDFLARE_CONFIGURATION_DIRECTORY
from scripts.deployment.transport_files import HostTransportFile
from scripts.deployment.units import CLOUDFLARE_SERVICE_UNIT, CLOUDFLARE_SERVICE_USER
from scripts.host_operations.config import HostOperationsConfig
from scripts.host_operations.probes import HostProbes

PUBLIC_ORIGIN = "https://polybotlab.com"
PRIVATE_ORIGIN = "https://host.example.ts.net"


def public_inventory(enabled=False):
    return inventory_values() | {
        "polybot_ingress": IngressMode.CLOUDFLARE,
        "polybot_origin": PUBLIC_ORIGIN,
        "polybot_tailnet_origin": PRIVATE_ORIGIN,
        "polybot_public_enabled": enabled,
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_public_flag_selects_auth_email_and_readiness_origin(enabled):
    inventory = DeploymentInventory.model_validate(public_inventory(enabled))
    values = inventory.model_dump(mode="json", by_alias=True)
    rendered = parse_values(render_template("runtime.env.j2", values))
    expected = PUBLIC_ORIGIN if enabled else PRIVATE_ORIGIN
    assert inventory.readiness_origin == rendered[AUTH_ORIGIN_ENV] == expected
    assert inventory.tailnet_origin == PRIVATE_ORIGIN


@pytest.mark.parametrize(
    "change",
    [
        {"polybot_ingress": "other"},
        {"polybot_ingress": IngressMode.TAILSCALE},
        {"polybot_tailnet_origin": None},
        {"polybot_tailnet_origin": PUBLIC_ORIGIN},
        {"polybot_public_enabled": "false"},
        {"polybot_origin": PRIVATE_ORIGIN},
        {"polybot_origin": "http://polybotlab.com"},
        {"polybot_origin": "https://polybotlab.com/"},
        {"polybot_origin": "https://polybotlab.com:8443"},
        {"polybot_origin": "https://127.0.0.1"},
    ],
)
def test_ingress_rejects_ambiguous_or_unsafe_configuration(change):
    with pytest.raises(ValueError):
        DeploymentInventory.model_validate(public_inventory() | change)


def test_legacy_inventory_and_host_config_remain_private():
    values = inventory_values()
    for name in ("ingress", "tailnet_origin", "public_enabled", "readiness_origin"):
        values.pop("polybot_" + name, None)
    inventory = DeploymentInventory.model_validate(values)
    assert inventory.readiness_origin == inventory.origin
    assert inventory.ingress is IngressMode.TAILSCALE
    assert (
        HostOperationsConfig.model_validate(host_config()).readiness_origin
        == PRIVATE_ORIGIN
    )
    with pytest.raises(ValueError):
        DeploymentInventory.model_validate(values | {"polybot_public_enabled": True})


@pytest.mark.parametrize("token", ["", " ", "token\n", "REPLACE_WITH_TUNNEL_TOKEN"])
def test_missing_token_fails_before_key_commands(monkeypatch, token):
    run = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    inputs = BootstrapInputs(
        ssh_public_key="ssh-ed25519 fixture",
        smtp_username="fixture",
        smtp_password="private-mail-password",
        cloudflare_tunnel_token=token,
    )
    with pytest.raises(ValueError, match="tunnel token"):
        inputs.require_valid(DeploymentInventory.model_validate(public_inventory()))
    run.assert_not_called()
    assert "private-mail-password" not in repr(inputs)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("connector_code", [0, 3, 4])
def test_host_monitor_requires_connector_state_and_private_management(
    monkeypatch, enabled, connector_code
):
    config = HostOperationsConfig.model_validate(
        host_config()
        | {
            "ingress": IngressMode.CLOUDFLARE,
            "origin": PUBLIC_ORIGIN,
            "tailnet_origin": PRIVATE_ORIGIN,
            "public_enabled": enabled,
        }
    )

    def command(args, **kwargs):
        result = (
            connector_code
            if args[-1] == CLOUDFLARE_SERVICE_UNIT
            else (1 if "is-failed" in args else 0)
        )
        return subprocess.CompletedProcess(args, result)

    monkeypatch.setattr(subprocess, "run", command)
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda args, **kwargs: json.dumps(
            serve_config()
            if "serve" in args
            else {
                "BackendState": "Running",
                "Self": {"DNSName": "host.example.ts.net."},
            }
        ).encode(),
    )
    if connector_code == (0 if enabled else 3):
        HostProbes(config).services()
    else:
        with pytest.raises(RuntimeError, match="connector"):
            HostProbes(config).services()


def test_release_rejects_inventory_changes_without_bootstrap():
    prepared = DeploymentInventory.model_validate(public_inventory())
    enabled = DeploymentInventory.model_validate(public_inventory(True))
    recorded = IngressSettings.model_validate(prepared.model_dump())
    prepared.require_bootstrapped(recorded, PRIVATE_ORIGIN)
    with pytest.raises(ValueError, match="bootstrap"):
        enabled.require_bootstrapped(recorded, PRIVATE_ORIGIN)
    with pytest.raises(ValueError, match="bootstrap"):
        prepared.require_bootstrapped(recorded, PUBLIC_ORIGIN)
    with pytest.raises(ValueError, match="bootstrap"):
        prepared.require_bootstrapped(recorded, PRIVATE_ORIGIN, prepared.http_port + 1)
    different_port = IngressSettings.model_validate(
        prepared.model_dump() | {"http_port": prepared.http_port + 1}
    )
    with pytest.raises(ValueError, match="bootstrap"):
        prepared.require_bootstrapped(different_port, PRIVATE_ORIGIN)


def test_systemd_uses_private_credential_file_and_no_token_in_argv():
    token = "fixture-secret-never-in-unit"
    unit = render_template(
        "cloudflared.service.j2", {"polybot_cloudflare_tunnel_token": token}
    )
    assert token not in unit
    assert str(HostTransportFile.CLOUDFLARE_TOKEN) in unit
    assert f"--token-file {CLOUDFLARE_CONFIGURATION_DIRECTORY}/" in unit
    assert f"User={CLOUDFLARE_SERVICE_USER}" in unit
    assert "Restart=on-failure" in unit
    tasks = yaml.safe_load(Path("deploy/ansible/tasks/cloudflare.yml").read_text())
    secret = next(
        task for task in tasks if task.get("name") == "Install protected tunnel token"
    )
    assert secret["no_log"] is True
    assert secret["ansible.builtin.copy"]["mode"] == "0640"
    assert secret["ansible.builtin.copy"]["owner"] == "root"


def test_release_public_gate_and_failure_closure_are_in_executed_playbook():
    tasks = yaml.safe_load(Path("deploy/ansible/tasks/activate.yml").read_text())
    gate = next(task for task in tasks if "rescue" in task)
    opening = gate["block"][0]
    evaluate = Environment().compile_expression(opening["when"])
    assert evaluate(polybot_public_enabled=False) is False
    assert evaluate(polybot_public_enabled=True) is True
    assert any(
        task.get("ansible.builtin.import_tasks") == "close-tunnel.yml"
        for task in gate["rescue"]
    )
    names = [task.get("name") for task in tasks]
    assert names.index("Require successful activation") < tasks.index(gate)
    checks = [
        task
        for task in tasks
        if task.get("ansible.builtin.import_tasks") == "verify-ingress.yml"
    ]
    assert len(checks) == 2
    assert "active_manifest" in checks[1]["vars"]["ingress_runtime_filename"]
    assert tasks.index(checks[1]) < tasks.index(gate)
    closing = next(
        i
        for i, task in enumerate(tasks)
        if task.get("ansible.builtin.import_tasks") == "close-tunnel.yml"
    )
    assert closing < names.index("Start activation independently of SSH lifetime")
