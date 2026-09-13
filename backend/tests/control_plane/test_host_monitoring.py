"""Alert state records SMTP acceptance and reports recoveries exactly once."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from scripts.host_operations import REQUIRED_ACTIVE_UNITS, HostOperations
from scripts.private_files import write_private


def test_failure_suppression_recovery_and_smtp_failure_retry(tmp_path, monkeypatch):
    write_private(
        tmp_path / "operations.json",
        json.dumps({"alert_to": "operator@example.com"}).encode(),
    )
    host = HostOperations(tmp_path)
    send = Mock()
    monkeypatch.setattr(subprocess, "run", send)
    host.notify("monitor", ["application"])
    host.notify("monitor", ["application"])
    assert send.call_count == 1
    host.notify("monitor", [])
    assert send.call_count == 2
    assert "RECOVERY" in send.call_args.kwargs["input"]
    send.side_effect = subprocess.CalledProcessError(1, "msmtp")
    with pytest.raises(subprocess.CalledProcessError):
        host.notify("monitor", ["application"])
    assert json.loads((tmp_path / ".alert-monitor.json").read_text()) == []
    send.side_effect = None
    host.notify("monitor", ["application"])
    assert send.call_count == 4


@pytest.mark.parametrize("inactive_unit", REQUIRED_ACTIVE_UNITS)
def test_monitor_rejects_any_inactive_required_unit(
    tmp_path, monkeypatch, inactive_unit
):
    write_private(tmp_path / "operations.json", b"{}")
    host = HostOperations(tmp_path)

    def systemctl(command, **kwargs):
        if command[-1] == inactive_unit:
            raise subprocess.CalledProcessError(3, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", systemctl)
    with pytest.raises(subprocess.CalledProcessError):
        host.services()


@pytest.mark.parametrize("returncode", [0, 1, 4])
def test_monitor_checks_failed_backup_units(tmp_path, monkeypatch, returncode):
    write_private(tmp_path / "operations.json", b"{}")
    host = HostOperations(tmp_path)

    def systemctl(command, **kwargs):
        result = returncode if "is-failed" in command else 0
        return subprocess.CompletedProcess(command, result)

    monkeypatch.setattr(subprocess, "run", systemctl)
    monkeypatch.setattr(
        subprocess, "check_output", lambda *args, **kwargs: b'{"Web": {"host:443": {}}}'
    )
    if returncode == 1:
        host.services()
    else:
        with pytest.raises(RuntimeError, match="backup unit"):
            host.services()
