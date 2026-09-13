"""Alert state records SMTP acceptance and reports accepted recovery transitions."""

import json
import subprocess
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

import pytest

from scripts.deployment.paths import OPERATIONS_CONFIGURATION_NAME
from scripts.deployment.runtime_contracts import DEFAULT_HTTP_PORT
from scripts.deployment.tailscale import PRIVATE_HTTPS_PORT
from scripts.host_operations import HostOperations, probes
from scripts.host_operations.__main__ import main
from scripts.host_operations.contracts import (
    REQUIRED_ACTIVE_UNITS,
    HostCheckCode,
    HostOperation,
)
from scripts.private_files import write_private


def test_failure_suppression_recovery_and_smtp_failure_retry(tmp_path, monkeypatch):
    write_private(
        tmp_path / OPERATIONS_CONFIGURATION_NAME,
        json.dumps(host_config()).encode(),
    )
    host = HostOperations(tmp_path)
    send = Mock()
    monkeypatch.setattr(subprocess, "run", send)
    host.alerts.notify(HostOperation.MONITOR, [HostCheckCode.APPLICATION])
    host.alerts.notify(HostOperation.MONITOR, [HostCheckCode.APPLICATION])
    assert send.call_count == 1
    host.alerts.notify(HostOperation.MONITOR, [])
    assert send.call_count == 2
    assert "RECOVERY" in send.call_args.kwargs["input"]
    send.side_effect = subprocess.CalledProcessError(1, "msmtp")
    with pytest.raises(subprocess.CalledProcessError):
        host.alerts.notify(HostOperation.MONITOR, [HostCheckCode.APPLICATION])
    assert json.loads((tmp_path / ".alert-monitor.json").read_text()) == []
    send.side_effect = None
    host.alerts.notify(HostOperation.MONITOR, [HostCheckCode.APPLICATION])
    assert send.call_count == 4


@pytest.mark.parametrize("inactive_unit", REQUIRED_ACTIVE_UNITS)
def test_monitor_rejects_any_inactive_required_unit(
    tmp_path, monkeypatch, inactive_unit
):
    write_private(
        tmp_path / OPERATIONS_CONFIGURATION_NAME, json.dumps(host_config()).encode()
    )
    host = HostOperations(tmp_path)

    def systemctl(command, **kwargs):
        if command[-1] == inactive_unit:
            raise subprocess.CalledProcessError(3, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", systemctl)
    with pytest.raises(subprocess.CalledProcessError):
        host.probes.services()


@pytest.mark.parametrize("returncode", [0, 1, 4])
def test_monitor_checks_failed_backup_units(tmp_path, monkeypatch, returncode):
    write_private(
        tmp_path / OPERATIONS_CONFIGURATION_NAME, json.dumps(host_config()).encode()
    )
    host = HostOperations(tmp_path)

    def systemctl(command, **kwargs):
        result = returncode if "is-failed" in command else 0
        return subprocess.CompletedProcess(command, result)

    monkeypatch.setattr(subprocess, "run", systemctl)
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
    if returncode == 1:
        host.probes.services()
    else:
        with pytest.raises(RuntimeError, match="backup unit"):
            host.probes.services()


def test_status_aggregates_each_failure_as_a_stable_code(tmp_path, monkeypatch):
    write_private(
        tmp_path / OPERATIONS_CONFIGURATION_NAME, json.dumps(host_config()).encode()
    )
    host = HostOperations(tmp_path)
    for owner, method in [
        (host, "application"),
        (host.probes, "services"),
        (host.probes, "https"),
        (host, "check_backup"),
    ]:
        monkeypatch.setattr(
            owner, method, Mock(side_effect=ValueError("private detail"))
        )
    assert host.status() == [
        HostCheckCode.APPLICATION,
        HostCheckCode.HOST_SERVICES,
        HostCheckCode.HTTPS_CERTIFICATE,
        HostCheckCode.BACKUP_FRESHNESS,
    ]


def test_pending_deployment_refuses_host_backup_before_snapshot(tmp_path, monkeypatch):
    write_private(
        tmp_path / OPERATIONS_CONFIGURATION_NAME, json.dumps(host_config()).encode()
    )
    host = HostOperations(tmp_path)
    monkeypatch.setattr(host.state, "pending", lambda: object())
    remote = Mock()
    monkeypatch.setattr(host, "remote", remote)
    with pytest.raises(RuntimeError, match="recovery is pending"):
        host.backup()
    remote.assert_not_called()


@pytest.mark.parametrize("operation", list(HostOperation))
def test_host_cli_maps_operations_and_sanitizes_configuration_failure(
    tmp_path, monkeypatch, capsys, operation
):
    monkeypatch.setattr("sys.argv", ["host", "--root", str(tmp_path), operation])
    write_private(
        tmp_path / OPERATIONS_CONFIGURATION_NAME, b'{"alert_to":"private-secret"}'
    )
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 1
    assert "private-secret" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "expiry,status", [(0, 200), (8 * 24 * 3600, 503), (8 * 24 * 3600, 200)]
)
def test_https_probe_checks_expiry_and_readiness(tmp_path, monkeypatch, expiry, status):

    write_private(
        tmp_path / OPERATIONS_CONFIGURATION_NAME, json.dumps(host_config()).encode()
    )
    host = HostOperations(tmp_path)
    socket = MagicMock()
    context = MagicMock()
    context.wrap_socket.return_value.__enter__.return_value.getpeercert.return_value = {
        "notAfter": "fixture"
    }
    monkeypatch.setattr(
        probes.socket, "create_connection", lambda *args, **kwargs: socket
    )
    monkeypatch.setattr(probes.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(
        probes.ssl,
        "cert_time_to_seconds",
        lambda _: datetime.now(UTC).timestamp() + expiry,
    )
    response = MagicMock()
    response.__enter__.return_value.status = status
    monkeypatch.setattr(
        probes.urllib.request, "urlopen", lambda *args, **kwargs: response
    )
    if expiry == 0 or status != 200:
        with pytest.raises(RuntimeError):
            host.probes.https()
    else:
        host.probes.https()


def host_config():
    return {
        "origin": "https://host.example.ts.net",
        "http_port": DEFAULT_HTTP_PORT,
        "alert_to": "operator@example.com",
        "remote": "backup:/backups/polybot",
    }


def serve_config():
    return {
        "TCP": {str(PRIVATE_HTTPS_PORT): {"HTTPS": True}},
        "Web": {
            f"host.example.ts.net:{PRIVATE_HTTPS_PORT}": {
                "Handlers": {"/": {"Proxy": f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"}}
            }
        },
    }
