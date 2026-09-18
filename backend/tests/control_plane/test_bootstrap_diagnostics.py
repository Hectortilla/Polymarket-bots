"""Secret-safe bootstrap diagnostics through the controller and real Ansible."""

import io
import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest
import yaml

from control_plane.test_cloudflare_deployment import public_inventory
from control_plane.test_deployment_contracts import inventory_values
from scripts.deployment import controller
from scripts.deployment.inventory import SUPPORTED_ARCHITECTURES, SUPPORTED_DISTRIBUTION
from scripts.deployment.paths import REPOSITORY

ANSIBLE = REPOSITORY / "deploy/ansible"
PRIVATE_MARKER = "do-not-disclose-private-fixture"


@pytest.fixture
def credentials():
    return {
        "ssh_public_key": "ssh-ed25519 " + PRIVATE_MARKER,
        "smtp_username": PRIVATE_MARKER,
        "smtp_password": PRIVATE_MARKER,
        "tailscale_authkey": "tskey-auth-" + PRIVATE_MARKER,
        "sftp_private_key": PRIVATE_MARKER,
        "sftp_known_hosts": PRIVATE_MARKER,
        "age_recipients": PRIVATE_MARKER,
    }


@pytest.fixture
def run_preflight(monkeypatch, capsys):
    def run(secrets, variables=None):
        monkeypatch.setattr(
            sys, "argv", ["controller", controller.ControllerOperation.BOOTSTRAP]
        )
        monkeypatch.setattr(
            sys,
            "stdin",
            io.StringIO(
                json.dumps(
                    {"variables": variables or inventory_values(), "secrets": secrets}
                )
            ),
        )
        with pytest.raises(SystemExit) as failure:
            controller.main()
        assert failure.value.code == 1
        captured = capsys.readouterr()
        assert not captured.err
        assert PRIVATE_MARKER not in captured.out
        return json.loads(captured.out)["error"]

    return run


@pytest.mark.parametrize(
    "field,value,diagnostic",
    [
        ("smtp_password", "", "polybot_smtp_password"),
        ("smtp_username", {PRIVATE_MARKER: PRIVATE_MARKER}, "polybot_smtp_username"),
        ("smtp_password", "  ", "SMTP credentials"),
        ("tailscale_authkey", PRIVATE_MARKER, "polybot_tailscale_authkey"),
        ("ssh_public_key", PRIVATE_MARKER, "polybot_ssh_public_key"),
        ("sftp_private_key", "", "SFTP credentials"),
    ],
)
def test_controller_reports_invalid_field_without_value(
    credentials, run_preflight, field, value, diagnostic
):
    assert diagnostic in run_preflight(credentials | {field: value})


def test_controller_reports_cloudflare_token_without_value(credentials, run_preflight):
    assert "polybot_cloudflare_tunnel_token" in run_preflight(
        credentials | {"cloudflare_tunnel_token": "REPLACE_" + PRIVATE_MARKER},
        public_inventory(),
    )


@pytest.mark.parametrize(
    "step,diagnostic",
    [
        (0, "polybot_ssh_public_key"),
        (1, "polybot_sftp_private_key"),
        (2, "parseable OpenSSH host records"),
        (3, "configured SFTP host and port"),
        (4, "polybot_age_recipients"),
    ],
)
def test_controller_identifies_failed_key_check(
    monkeypatch, credentials, run_preflight, step, diagnostic
):
    failure = subprocess.CalledProcessError(
        1, [PRIVATE_MARKER], output=PRIVATE_MARKER, stderr=PRIVATE_MARKER
    )
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=[None] * step + [failure]))
    assert diagnostic in run_preflight(credentials)


@pytest.mark.parametrize(
    "step,failure,diagnostic",
    [
        (0, FileNotFoundError(PRIVATE_MARKER), "Install ssh-keygen on the controller"),
        (4, FileNotFoundError(PRIVATE_MARKER), "Install age on the controller"),
        (0, subprocess.TimeoutExpired(PRIVATE_MARKER, 30), "validation timed out"),
        (0, PermissionError(PRIVATE_MARKER), "controller prerequisites"),
    ],
)
def test_controller_reports_tool_failure_without_raw_exception(
    monkeypatch, credentials, run_preflight, step, failure, diagnostic
):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=[None] * step + [failure]))
    assert diagnostic in run_preflight(credentials)


def test_controller_hides_inventory_validation_details(credentials, run_preflight):
    assert "private configuration" in run_preflight(
        credentials, inventory_values() | {"polybot_arch": PRIVATE_MARKER}
    )


@pytest.mark.parametrize(
    "invalid_field", [None, "ssh_public_key", "tailscale_authkey", "controller"]
)
def test_real_ansible_preflight_stops_safely_without_deprecation(
    tmp_path, invalid_field, credentials
):
    key = tmp_path / "key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
        capture_output=True,
    )
    secrets = credentials | {"ssh_public_key": key.with_suffix(".pub").read_text()}
    if invalid_field and invalid_field != "controller":
        secrets[invalid_field] = PRIVATE_MARKER
    variables = inventory_values() | {
        "polybot_backups_enabled": False,
        **{"polybot_" + key: value for key, value in secrets.items()},
    }
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {"all": {"children": {"polybot": {"hosts": {"fixture": variables}}}}}
        )
    )
    marker = tmp_path / "host-mutation"
    preflight_tasks = yaml.safe_load(
        (ANSIBLE / "tasks/bootstrap-preflight.yml").read_text()
    )
    if invalid_field == "controller":
        preflight_tasks[0]["ansible.builtin.command"]["argv"] = [
            sys.executable,
            "-c",
            f"import sys; sys.stderr.write({PRIVATE_MARKER!r}); sys.exit(1)",
        ]
    play = tmp_path / "verify.yml"
    play.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "polybot",
                    "gather_facts": False,
                    "connection": "local",
                    "vars": {
                        "ansible_distribution": SUPPORTED_DISTRIBUTION,
                        "ansible_architecture": SUPPORTED_ARCHITECTURES[
                            variables["polybot_arch"]
                        ],
                        # Must not evaluate unrelated variables while collecting inputs.
                        "unrelated": "{{ nonexistent_variable }}",
                    },
                    "tasks": [
                        {
                            "ansible.builtin.import_tasks": str(
                                ANSIBLE / "tasks/validate.yml"
                            )
                        },
                        *preflight_tasks,
                        {
                            "ansible.builtin.file": {
                                "path": str(marker),
                                "state": "touch",
                            }
                        },
                    ],
                }
            ]
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "ansible.cli.playbook", "-i", str(inventory), str(play)],
        cwd=REPOSITORY,
        env={**os.environ, "ANSIBLE_CONFIG": str(ANSIBLE / "ansible.cfg")},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    output = result.stdout + result.stderr
    assert PRIVATE_MARKER not in output
    assert "play_hosts" not in output
    if invalid_field:
        assert result.returncode != 0, output
        assert (
            "Bootstrap controller could not run"
            if invalid_field == "controller"
            else "polybot_" + invalid_field
        ) in output
        assert not marker.exists()
    else:
        assert result.returncode == 0, output
        assert marker.exists()
