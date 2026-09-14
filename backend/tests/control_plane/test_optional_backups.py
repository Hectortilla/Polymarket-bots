"""Backup opt-out at controller, Ansible rendering and host-operation boundaries."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

from control_plane.test_deployment_contracts import inventory_values
from control_plane.test_host_monitoring import host_config, serve_config
from scripts.deployment.ansible_contract import deployment_contract
from scripts.deployment.bootstrap_inputs import BootstrapInputs
from scripts.deployment.inventory import DeploymentInventory
from scripts.deployment.paths import OPERATIONS_CONFIGURATION_NAME
from scripts.host_operations import HostOperations
from scripts.host_operations.config import HostOperationsConfig
from scripts.host_operations.contracts import (
    BACKUP_SERVICE_UNITS,
    BACKUP_TIMER_UNITS,
    REQUIRED_ACTIVE_UNITS,
    HostCheckCode,
    HostOperation,
)
from scripts.private_files import write_private


def disabled_inventory():
    return {
        name: value
        for name, value in inventory_values().items()
        if not name.startswith("polybot_sftp_")
    } | {"polybot_backups_enabled": False}


def test_example_inventory_needs_no_backup_configuration():
    values = yaml.safe_load(Path("deploy/ansible/inventory/example.yml").read_text())[
        "all"
    ]["children"]["polybot"]["vars"]
    inventory = DeploymentInventory.model_validate(
        values | {"polybot_origin": "https://fixture.example.ts.net"}
    )
    assert not inventory.backups_enabled
    assert inventory.sftp_host is None


@pytest.mark.parametrize("enabled", [True, None])
def test_missing_sftp_requires_explicit_opt_out(enabled):
    values = disabled_inventory()
    if enabled is None:
        values.pop("polybot_backups_enabled")
    else:
        values["polybot_backups_enabled"] = enabled
    with pytest.raises(ValueError, match="SFTP destination"):
        DeploymentInventory.model_validate(values)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_backup_opt_out_requires_a_yaml_boolean(value):
    with pytest.raises(ValueError):
        DeploymentInventory.model_validate(
            inventory_values() | {"polybot_backups_enabled": value}
        )
    with pytest.raises(ValueError):
        HostOperationsConfig.model_validate(host_config() | {"backups_enabled": value})


def test_old_inventory_and_host_config_keep_backups_enabled():
    values = inventory_values()
    values.pop("polybot_backups_enabled")
    assert DeploymentInventory.model_validate(values).backups_enabled
    assert HostOperationsConfig.model_validate(host_config()).backups_enabled


def test_disabled_bootstrap_validates_deployment_key_without_age(tmp_path, monkeypatch):
    key = tmp_path / "deployment-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    inputs = BootstrapInputs(
        ssh_public_key=key.with_suffix(".pub").read_text(),
        smtp_username="fixture",
        smtp_password="password",
        enroll_tailnet=False,
    )
    run = Mock(wraps=subprocess.run)
    monkeypatch.setattr(subprocess, "run", run)
    inputs.require_valid(DeploymentInventory.model_validate(disabled_inventory()))
    assert len(run.call_args_list) == 1
    assert run.call_args.args[0][:2] == ["ssh-keygen", "-l"]
    with pytest.raises(ValueError, match="SFTP credentials"):
        inputs.require_valid(DeploymentInventory.model_validate(inventory_values()))


@pytest.mark.parametrize("enabled", [False, True])
def test_ansible_operations_config_renders_without_unused_sftp_values(enabled):
    values = inventory_values() if enabled else disabled_inventory()
    tasks = yaml.safe_load(Path("deploy/ansible/bootstrap.yml").read_text())[0]["tasks"]
    task = next(
        task
        for task in tasks
        if task.get("name") == "Install host operational configuration"
    )
    env = Environment(undefined=StrictUndefined)
    env.filters["to_nice_json"] = json.dumps
    config = HostOperationsConfig.model_validate_json(
        env.from_string(task["ansible.builtin.copy"]["content"]).render(
            **values, deployment_contract=deployment_contract()
        )
    )
    assert config.backups_enabled is enabled
    assert (config.remote is not None) is enabled


def test_host_config_requires_remote_unless_explicitly_disabled():
    config = host_config()
    config.pop("remote")
    with pytest.raises(ValueError, match="backup remote"):
        HostOperationsConfig.model_validate(config)
    assert (
        HostOperationsConfig.model_validate(config | {"backups_enabled": False}).remote
        is None
    )


@pytest.fixture
def disabled_host(tmp_path):
    config = host_config() | {"backups_enabled": False}
    config.pop("remote")
    write_private(tmp_path / OPERATIONS_CONFIGURATION_NAME, json.dumps(config).encode())
    return HostOperations(tmp_path)


def test_disabled_status_keeps_application_checks_without_remote_access(
    disabled_host, monkeypatch, capsys
):
    for owner, method in [
        (disabled_host, "application"),
        (disabled_host.probes, "services"),
        (disabled_host.probes, "https"),
    ]:
        monkeypatch.setattr(owner, method, Mock())
    remote = Mock(side_effect=AssertionError("must not access backup storage"))
    monkeypatch.setattr(disabled_host, "remote", remote)
    assert disabled_host.execute(HostOperation.STATUS) == []
    assert '"backups_enabled": false' in capsys.readouterr().out
    remote.assert_not_called()
    disabled_host.application.assert_called_once()
    disabled_host.probes.services.assert_called_once()
    disabled_host.probes.https.assert_called_once()
    disabled_host.application.side_effect = RuntimeError("unhealthy")
    assert disabled_host.status() == [HostCheckCode.APPLICATION]


@pytest.mark.parametrize(
    "operation", [HostOperation.BACKUP, HostOperation.BACKUP_CHECK]
)
def test_disabled_explicit_backup_fails_without_alert_or_snapshot(
    disabled_host, monkeypatch, operation, capsys
):
    backup = Mock()
    notify = Mock()
    monkeypatch.setattr(disabled_host, "backup", backup)
    monkeypatch.setattr(disabled_host.alerts, "notify", notify)
    assert disabled_host.execute(operation) == [HostCheckCode.BACKUPS_DISABLED]
    assert "Backups are disabled" in capsys.readouterr().out
    backup.assert_not_called()
    notify.assert_not_called()


def test_disabled_direct_backup_refuses_before_release_or_transport(
    disabled_host, monkeypatch
):
    release = Mock()
    monkeypatch.setattr(disabled_host, "release", release)
    for operation in (disabled_host.backup, disabled_host.remote):
        with pytest.raises(RuntimeError, match="backups are disabled"):
            operation()
    release.assert_not_called()


def test_disabled_probe_ignores_backup_units_but_checks_monitor(
    disabled_host, monkeypatch
):
    def systemctl(command, **kwargs):
        assert not set(command).intersection(
            (*BACKUP_TIMER_UNITS, *BACKUP_SERVICE_UNITS)
        )
        return subprocess.CompletedProcess(command, 1 if "is-failed" in command else 0)

    run = Mock(side_effect=systemctl)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda command, **kwargs: json.dumps(
            serve_config()
            if "serve" in command
            else {
                "BackendState": "Running",
                "Self": {"DNSName": "host.example.ts.net."},
            }
        ).encode(),
    )
    disabled_host.probes.services()
    active = [
        call.args[0][-1] for call in run.call_args_list if "is-active" in call.args[0]
    ]
    assert active == [
        unit for unit in REQUIRED_ACTIVE_UNITS if unit not in BACKUP_TIMER_UNITS
    ]
