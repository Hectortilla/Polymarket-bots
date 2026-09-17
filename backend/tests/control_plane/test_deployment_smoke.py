"""Keep failed rehearsal commands diagnosable without disclosing credentials."""

import subprocess
from unittest.mock import Mock

import pytest

from control_plane import deployment_smoke
from scripts.local_docker import LocalDocker


@pytest.fixture
def smoke(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment_smoke, "REPOSITORY", tmp_path)
    monkeypatch.setattr(
        LocalDocker, "from_context", lambda: LocalDocker("unix:///unused.sock")
    )
    return deployment_smoke.DeploymentSmoke()


@pytest.mark.parametrize("returncode", [0, 1])
def test_command_reports_failure_output_and_preserves_exit_status(
    smoke, monkeypatch, capsys, returncode
):
    output = "browser assertion details\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess(["npm"], returncode, output)),
    )
    if returncode:
        with pytest.raises(subprocess.CalledProcessError) as failure:
            smoke.command("npm")
        assert failure.value.returncode == returncode
        assert capsys.readouterr().out == output
    else:
        assert smoke.command("npm") == output
        assert capsys.readouterr().out == ""
    assert (smoke.directory / "commands.log").read_text() == output


def test_failed_command_rejects_sensitive_output_before_logging_or_printing(
    smoke, monkeypatch, capsys
):
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                ["npm"], 1, deployment_smoke.TEST_PASSWORD
            )
        ),
    )
    with pytest.raises(AssertionError, match="exposed an acceptance credential"):
        smoke.command("npm")
    assert capsys.readouterr().out == ""
    assert (smoke.directory / "commands.log").read_text() == ""
