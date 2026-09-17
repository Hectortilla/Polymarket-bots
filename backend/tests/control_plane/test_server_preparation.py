"""Host-policy input and SSH lockout guards used by Ansible bootstrap."""

import base64
import json
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from control_plane.test_deployment_contracts import inventory_values
from scripts.deployment import controller
from scripts.deployment.ansible_contract import deployment_contract
from scripts.deployment.inventory import (
    SUPPORTED_ARCHITECTURES,
    SUPPORTED_DISTRIBUTION,
    DeploymentInventory,
)
from scripts.deployment.paths import REPOSITORY
from scripts.deployment.ssh_access import (
    DEPLOYMENT_SSH_USER,
    SSH_HARDENING_POLICY,
    SSH_PROBE_TIMEOUT_SECONDS,
    DeploymentSSHAccess,
    SSHConnectionContext,
    require_hardened_ssh,
)

ANSIBLE = REPOSITORY / "deploy/ansible"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ignore_lid", "false"),
        ("manage_swap", 1),
        ("admin_user", "root"),
        ("admin_user", "invalid user"),
        ("swap_size_mib", True),
        ("swap_size_mib", 0),
        ("swap_size_mib", 127),
        ("swappiness", -1),
        ("swappiness", 101),
        ("swappiness", "10"),
    ],
)
def test_host_policy_rejects_invalid_inputs_before_bootstrap(field, value):
    with pytest.raises(ValueError):
        DeploymentInventory.model_validate(
            inventory_values() | {f"polybot_{field}": value}
        )


def test_optional_host_policy_is_normalized_for_ansible():
    inventory = DeploymentInventory.model_validate(
        inventory_values()
        | {
            "polybot_admin_user": "hec",
            "polybot_ignore_lid": True,
            "polybot_manage_swap": False,
            "polybot_swap_size_mib": 512,
        }
    )
    normalized = inventory.model_dump(by_alias=True)
    assert normalized["polybot_admin_user"] == "hec"
    assert normalized["polybot_ignore_lid"] is True
    assert normalized["polybot_manage_swap"] is False
    assert normalized["polybot_swap_size_mib"] == 512


@pytest.mark.parametrize("explicit_host_policy", [False, True])
def test_real_ansible_installs_normalized_values_and_omitted_defaults(
    tmp_path, explicit_host_policy
):
    values = inventory_values() | {"polybot_smtp_host": "SMTP.Example.COM."}
    if explicit_host_policy:
        values.update(
            polybot_admin_user="hec",
            polybot_ignore_lid=True,
            polybot_manage_swap=False,
            polybot_swap_size_mib=512,
        )
    normalized = DeploymentInventory.model_validate(values).model_dump(
        mode="json", by_alias=True
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "all": {
                    "children": {
                        "polybot": {
                            "hosts": {
                                "fixture": values
                                | {
                                    "ansible_connection": "local",
                                    "ansible_python_interpreter": sys.executable,
                                }
                            }
                        }
                    }
                }
            }
        )
    )
    play = tmp_path / "verify.yml"
    play.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Verify the real inventory-to-Ansible boundary",
                    "hosts": "polybot",
                    "gather_facts": False,
                    "vars": {
                        "ansible_distribution": SUPPORTED_DISTRIBUTION,
                        "ansible_architecture": SUPPORTED_ARCHITECTURES[
                            values["polybot_arch"]
                        ],
                        "expected_normalized": normalized,
                    },
                    "tasks": [
                        {
                            "ansible.builtin.import_tasks": str(
                                ANSIBLE / "tasks/validate.yml"
                            )
                        },
                        {
                            "ansible.builtin.assert": {
                                "that": "lookup('ansible.builtin.vars', item.key) == item.value",
                            },
                            "loop": "{{ expected_normalized | dict2items }}",
                            "loop_control": {"label": "{{ item.key }}"},
                        },
                    ],
                }
            ],
            sort_keys=False,
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
    assert result.returncode == 0, result.stdout + result.stderr


def test_ssh_proof_uses_fresh_key_only_connection_and_preserves_quoted_routes(
    monkeypatch,
):
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, f"192.0.2.10 1234 192.0.2.20 2222\n{DEPLOYMENT_SSH_USER}\n0\n"
        )
    )
    monkeypatch.setattr(subprocess, "run", run)
    probe = DeploymentSSHAccess(
        host="server.example",
        port=2222,
        private_key_file="/keys/deploy key",
        common_args='-o UserKnownHostsFile="/keys/known hosts" -J gateway.example -o ControlPath=existing',
    )
    context = probe.verify()
    command = run.call_args.args[0]
    assert command.index("ControlPath=none") < command.index("ControlPath=existing")
    for option in [
        "ControlMaster=no",
        "BatchMode=yes",
        "PreferredAuthentications=publickey",
        "StrictHostKeyChecking=yes",
    ]:
        assert option in command
    assert "UserKnownHostsFile=/keys/known hosts" in command
    assert command[command.index("-i") + 1] == "/keys/deploy key"
    assert command[command.index("-l") + 1] == DEPLOYMENT_SSH_USER
    assert run.call_args.kwargs["timeout"] == SSH_PROBE_TIMEOUT_SECONDS
    assert run.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert context.server_port == 2222
    assert context.sshd_selector().startswith(f"user={DEPLOYMENT_SSH_USER},")


@pytest.mark.parametrize("override_host", [False, True])
def test_real_ansible_ssh_proof_resolves_relative_paths_from_repository(
    tmp_path, override_host
):
    captured = tmp_path / "ssh-command.json"
    ssh = tmp_path / "ssh"
    ssh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"Path({str(captured)!r}).write_text(json.dumps("
        "{'cwd': os.getcwd(), 'argv': sys.argv[1:]}))\n"
        f"print('192.0.2.1 1234 192.0.2.2 22 {DEPLOYMENT_SSH_USER} 0')\n"
    )
    ssh.chmod(0o755)
    play = tmp_path / "probe.yml"
    play.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "fixture",
                    "gather_facts": False,
                    "vars": {
                        "ansible_host": "inventory.example",
                        "ansible_ssh_common_args": "-o UserKnownHostsFile=./known_hosts",
                        "polybot_ssh_private_key_file": "./deployment-key",
                    },
                    "tasks": [
                        {
                            "ansible.builtin.import_tasks": str(
                                ANSIBLE / "tasks/ssh-access.yml"
                            )
                        }
                    ],
                }
            ]
        )
    )
    command = [
        sys.executable,
        "-m",
        "ansible.cli.playbook",
        "-i",
        "fixture,",
        str(play),
    ]
    if override_host:
        command.extend(["-e", "ansible_host=override.example"])
    result = subprocess.run(
        command,
        cwd=REPOSITORY,
        env={
            **os.environ,
            "ANSIBLE_CONFIG": str(ANSIBLE / "ansible.cfg"),
            "UV_PROJECT": str(REPOSITORY),
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    invocation = json.loads(captured.read_text())
    assert invocation["cwd"] == str(REPOSITORY)
    arguments = invocation["argv"]
    assert "UserKnownHostsFile=./known_hosts" in arguments
    assert arguments[arguments.index("-i") + 1] == "deployment-key"
    expected_host = "override.example" if override_host else "inventory.example"
    assert arguments[arguments.index("--") + 1] == expected_host


def test_controller_reports_ssh_failure_without_exposing_subprocess_output(
    monkeypatch, capsys, tmp_path
):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"host": "server.example"}))
    monkeypatch.setattr(
        sys, "argv", ["controller", controller.ControllerOperation.SSH_ACCESS]
    )
    monkeypatch.setattr(
        DeploymentSSHAccess,
        "verify",
        Mock(
            side_effect=subprocess.CalledProcessError(
                255, "ssh", stderr="private-output"
            )
        ),
    )
    with request.open() as stdin:
        monkeypatch.setattr(sys, "stdin", stdin)
        with pytest.raises(SystemExit) as failure:
            controller.main()
    assert failure.value.code == 1
    stderr = capsys.readouterr().err
    assert "SSH/sudo verification failed" in stderr
    assert "known_hosts" in stderr
    assert "private-output" not in stderr


@pytest.mark.parametrize(
    "output",
    [
        "",
        "0",
        f"192.0.2.1 123 192.0.2.2 22 {DEPLOYMENT_SSH_USER} 1000",
        f"bad 123 192.0.2.2 22 {DEPLOYMENT_SSH_USER} 0",
        f"192.0.2.1 123 192.0.2.2 0 {DEPLOYMENT_SSH_USER} 0",
        "192.0.2.1 123 192.0.2.2 22 root 0",
    ],
)
def test_ssh_proof_requires_valid_connection_context_and_root_sudo(output):
    with pytest.raises(ValueError):
        SSHConnectionContext.from_probe(output)


def test_unavailable_ssh_or_sudo_is_a_bootstrap_failure(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=subprocess.CalledProcessError(255, "ssh"))
    )
    with pytest.raises(subprocess.CalledProcessError):
        DeploymentSSHAccess(host="host.example").verify()


@pytest.mark.parametrize("conflicting_key", list(SSH_HARDENING_POLICY))
def test_each_effective_ssh_policy_conflict_is_rejected(conflicting_key):
    policy = SSH_HARDENING_POLICY | {conflicting_key: "unexpected"}
    with pytest.raises(ValueError, match="key-only"):
        require_hardened_ssh(
            "\n".join(f"{key.lower()} {value}" for key, value in policy.items())
        )


def test_ssh_templates_override_early_defaults_without_duplicate_includes():
    env = Environment(
        loader=FileSystemLoader(ANSIBLE / "templates"), undefined=StrictUndefined
    )
    env.filters["b64decode"] = lambda text: base64.b64decode(text).decode()
    contract = deployment_contract()
    original = f"PasswordAuthentication yes\nInclude {contract['sshd_hardening']}\nMatch User other\n    PasswordAuthentication yes\n"
    template = env.get_template("sshd_config.j2")
    rendered = template.render(
        deployment_contract=contract,
        ssh_original_main={"content": base64.b64encode(original.encode()).decode()},
    )
    include = f"Include {contract['sshd_hardening']}"
    assert rendered.splitlines()[0] == include
    assert rendered.splitlines().count(include) == 1
    assert "Match User other\n    PasswordAuthentication yes" in rendered
    assert (
        template.render(
            deployment_contract=contract,
            ssh_original_main={"content": base64.b64encode(rendered.encode()).decode()},
        )
        == rendered
    )
    policy = env.get_template("ssh-hardening.conf.j2").render(
        deployment_contract=contract
    )
    require_hardened_ssh(policy.lower())


@pytest.mark.parametrize(
    "filesystem,stat,accepted",
    [
        ("ext4", {"exists": False}, True),
        ("btrfs", {"exists": False}, False),
        (
            "xfs",
            {"exists": True, "isreg": True, "nlink": 1, "size": 512 * 1024**2},
            True,
        ),
        ("ext4", {"exists": True, "isreg": False}, False),
        (
            "ext4",
            {"exists": True, "isreg": True, "nlink": 2, "size": 512 * 1024**2},
            False,
        ),
        ("ext4", {"exists": True, "isreg": True, "nlink": 1, "size": 1}, False),
    ],
)
def test_ansible_swap_guards_reject_unsafe_storage(filesystem, stat, accepted):
    tasks = yaml.safe_load((ANSIBLE / "tasks/swap.yml").read_text())
    guard = next(
        task
        for task in tasks
        if task.get("name")
        == "Require supported swap storage without resizing existing files"
    )
    env = Environment(undefined=StrictUndefined)
    results = [
        env.compile_expression(expression)(
            swap_filesystem={"stdout": filesystem},
            swap_file={"stat": stat},
            polybot_swap_size_mib=512,
        )
        for expression in guard["ansible.builtin.assert"]["that"]
    ]
    assert all(results) is accepted


@pytest.mark.parametrize(
    "entry,accepted",
    [
        ([], True),
        (["/swapfile none swap sw 0 0"], True),
        (["/swapfile none swap noauto 0 0"], False),
        (["/swapfile none ext4 defaults 0 0"], False),
        (["/swapfile"], False),
        (["/swapfile none swap sw 0 0"] * 2, False),
    ],
)
def test_ansible_swap_fstab_guard_rejects_ambiguous_persistence(entry, accepted):
    tasks = yaml.safe_load((ANSIBLE / "tasks/swap.yml").read_text())
    guard = next(
        task
        for task in tasks
        if task.get("name") == "Refuse duplicate or conflicting swapfile entries"
    )
    env = Environment(undefined=StrictUndefined)
    assert (
        all(
            env.compile_expression(expression)(swap_fstab_entries=entry)
            for expression in guard["ansible.builtin.assert"]["that"]
        )
        is accepted
    )
