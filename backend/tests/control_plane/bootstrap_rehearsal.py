"""Two-pass preparation on an isolated Debian systemd container, no tailnet account."""

import argparse
import json
import os
import shutil
import subprocess
import time
from uuid import uuid4

import yaml

from control_plane.activation_rehearsal import ActivationRehearsal
from scripts.deployment.ansible_contract import deployment_contract
from scripts.deployment.ingress import IngressMode
from scripts.deployment.inventory import SUPPORTED_ARCHITECTURES
from scripts.deployment.paths import (
    CLOUDFLARE_CONFIGURATION_DIRECTORY,
    DEFAULT_APP_DIRECTORY,
    REPOSITORY,
)
from scripts.deployment.runtime_contracts import DEFAULT_HTTP_PORT
from scripts.deployment.ssh_access import (
    DEPLOYMENT_SSH_USER,
    SSHD_HARDENING_PATH,
    SSHD_MAIN_PATH,
)
from scripts.deployment.transport_files import HostTransportFile
from scripts.deployment.units import (
    CLOUDFLARE_SERVICE_UNIT,
    CLOUDFLARE_SERVICE_USER,
    MONITOR_TIMER_UNIT,
)
from scripts.host_operations.contracts import BACKUP_TIMER_UNITS
from scripts.local_docker import LocalDocker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host-only",
        action="store_true",
        help="Check bootstrap and SSH guards without release/backup rehearsals.",
    )
    parser.add_argument("--initial-access", choices=("root", "su"), default="root")
    parser.add_argument(
        "--ingress", choices=list(IngressMode), default=IngressMode.TAILSCALE
    )
    args = parser.parse_args()
    docker = LocalDocker.from_context().output
    name = "polybot-bootstrap-test-" + uuid4().hex[:10]
    directory = REPOSITORY / "data" / "beta" / name
    directory.mkdir(parents=True, mode=0o700)
    key = directory / "id_ed25519"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )

    docker("build", "-t", name, "-f", "deploy/rehearsal/Dockerfile", "deploy/rehearsal")
    try:
        docker(
            "run",
            "-d",
            "--privileged",
            "--cgroupns=private",
            "--tmpfs",
            "/run",
            "--tmpfs",
            "/run/lock",
            "-p",
            "127.0.0.1::22",
            "--name",
            name,
            name,
        )
        docker("exec", name, "mkdir", "-p", "/root/.ssh")
        docker("cp", str(key.with_suffix(".pub")), name + ":/root/.ssh/authorized_keys")
        docker("exec", name, "chown", "-R", "root:root", "/root/.ssh")
        docker("exec", name, "chmod", "600", "/root/.ssh/authorized_keys")
        docker("exec", name, "useradd", "--create-home", "hec")
        if args.initial_access == "su":
            docker(
                "exec", "-i", name, "chpasswd", input="root:disposable-root-password\n"
            )
            docker("exec", name, "cp", "-a", "/root/.ssh", "/home/hec/.ssh")
            docker("exec", name, "chown", "-R", "hec:hec", "/home/hec/.ssh")
        docker(
            "exec",
            name,
            "sh",
            "-c",
            "printf '# retained comment\\ndeb [signed-by=/etc/apt/keyrings/tailscale.gpg] https://pkgs.tailscale.com/stable/debian bookworm main\\n' > /etc/apt/sources.list.d/pkgs_tailscale_com_stable_debian.list",
        )
        port = docker("port", name, "22/tcp").split(":")[-1]
        public_host_key = docker(
            "exec", name, "cat", "/etc/ssh/ssh_host_ed25519_key.pub"
        )
        known = directory / "known_hosts"
        known.write_text(f"[127.0.0.1]:{port} {public_host_key}\n")
        subprocess.run(
            ["age-keygen", "-o", str(directory / "age.key")],
            check=True,
            capture_output=True,
        )
        variables = {
            "ansible_host": "127.0.0.1",
            "ansible_port": int(port),
            "ansible_user": "root",
            "ansible_ssh_private_key_file": str(key),
            "ansible_ssh_common_args": f"-o UserKnownHostsFile={known} -o StrictHostKeyChecking=yes",
            "polybot_root": str(DEFAULT_APP_DIRECTORY),
            "polybot_arch": {
                machine: arch for arch, machine in SUPPORTED_ARCHITECTURES.items()
            }[docker("exec", name, "uname", "-m")],
            "polybot_origin": "https://fixture.example.ts.net",
            "polybot_http_port": DEFAULT_HTTP_PORT,
            "polybot_manage_swap": False,  # Container overlay and kernel swap are not host acceptance.
            "polybot_ignore_lid": True,
            "polybot_admin_user": "hec",
            "polybot_smtp_host": "localhost",
            "polybot_smtp_port": 1025,
            "polybot_smtp_security": "starttls",
            "polybot_smtp_from": "accounts@example.com",
            "polybot_alert_to": "operator@example.com",
            "polybot_sftp_host": "sftp.invalid",
            "polybot_sftp_port": 22,
            "polybot_sftp_user": "fixture",
            "polybot_sftp_directory": "/backups/polybot",
            "polybot_ssh_public_key": key.with_suffix(".pub").read_text(),
            "polybot_smtp_username": "fixture",
            "polybot_smtp_password": "fixture-password",
            "polybot_sftp_private_key": key.read_text(),
            "polybot_sftp_known_hosts": f"sftp.invalid {public_host_key}\n",
            "polybot_age_recipients": subprocess.check_output(
                ["age-keygen", "-y", str(directory / "age.key")], text=True
            ).strip(),
        }
        if args.ingress == IngressMode.CLOUDFLARE:
            variables.update(
                polybot_ingress=IngressMode.CLOUDFLARE,
                polybot_origin="https://polybotlab.example",
                polybot_tailnet_origin=variables["polybot_origin"],
                polybot_public_enabled=False,
                polybot_cloudflare_tunnel_token="fixture-token-not-connected-to-cloudflare",
            )
        if args.initial_access == "su":
            variables.update(
                ansible_user="hec",
                ansible_become_method="su",
                ansible_become_password="disposable-root-password",
            )
        inventory = directory / "inventory.json"
        inventory.write_text(
            json.dumps(
                {
                    "all": {
                        "children": {
                            "polybot": {
                                "hosts": {
                                    "fixture": backup_variables(
                                        variables, enabled=False
                                    )
                                }
                            }
                        }
                    }
                }
            )
        )
        inventory.chmod(0o600)
        command = [
            "ansible-playbook",
            "-i",
            str(inventory),
            "deploy/ansible/bootstrap.yml",
            "--skip-tags",
            "tailnet",
        ]
        env = {
            **os.environ,
            "ANSIBLE_CONFIG": str(REPOSITORY / "deploy/ansible/ansible.cfg"),
        }
        snapshots = []
        service_snapshots = []
        for attempt in (1, 2):
            with (directory / f"bootstrap-{attempt}.log").open("w") as output:
                subprocess.run(
                    command,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            if attempt == 1:
                variables["ansible_user"] = "polybot"
                variables.pop("ansible_become_method", None)
                variables.pop("ansible_become_password", None)
                updated_inventory = json.loads(inventory.read_text())
                updated_inventory["all"]["children"]["polybot"]["hosts"]["fixture"] = (
                    backup_variables(variables, enabled=False)
                )
                inventory.write_text(json.dumps(updated_inventory))
                docker(
                    "exec",
                    name,
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    "sentinel",
                    "--mount",
                    "source=sentinel,target=/data",
                    "busybox:1.37",
                    "sh",
                    "-c",
                    "echo retained >/data/value; sleep 99999",
                )
            service_snapshots.append(
                docker(
                    "exec",
                    name,
                    "docker",
                    "inspect",
                    "--format",
                    "{{.Id}} {{.State.StartedAt}}",
                    "sentinel",
                )
            )
            snapshots.append(
                docker(
                    "exec", name, "sha256sum", "/srv/polybot/secrets/postgres_password"
                )
            )
        assert snapshots[0] == snapshots[1]
        assert service_snapshots[0] == service_snapshots[1]
        if args.ingress == IngressMode.CLOUDFLARE:
            token_path = str(
                CLOUDFLARE_CONFIGURATION_DIRECTORY / HostTransportFile.CLOUDFLARE_TOKEN
            )
            assert (
                docker("exec", name, "stat", "-c", "%a %U %G", token_path)
                == f"640 root {CLOUDFLARE_SERVICE_USER}"
            )
            docker(
                "exec",
                name,
                "runuser",
                "-u",
                CLOUDFLARE_SERVICE_USER,
                "--",
                "sh",
                "-c",
                'test ! -w "$1" && head -c 1 "$1" >/dev/null',
                "token-check",
                token_path,
            )
            unit = docker("exec", name, "systemctl", "cat", CLOUDFLARE_SERVICE_UNIT)
            assert variables["polybot_cloudflare_tunnel_token"] not in unit
            assert "--token-file" in unit
            state = docker(
                "exec",
                name,
                "systemctl",
                "show",
                CLOUDFLARE_SERVICE_UNIT,
                "--property=ActiveState",
                "--value",
            )
            assert state == "inactive"
            assert (
                docker(
                    "exec",
                    name,
                    "systemctl",
                    "show",
                    CLOUDFLARE_SERVICE_UNIT,
                    "--property=UnitFileState",
                    "--value",
                )
                == "disabled"
            )
        assert (
            docker("exec", name, "docker", "exec", "sentinel", "cat", "/data/value")
            == "retained"
        )
        ssh = [
            "ssh",
            "-i",
            str(key),
            "-p",
            port,
            "-o",
            f"UserKnownHostsFile={known}",
            "-o",
            "StrictHostKeyChecking=yes",
            f"{DEPLOYMENT_SSH_USER}@127.0.0.1",
        ]
        try:
            subprocess.run(
                [
                    *ssh,
                    "sudo -n systemd-run --unit=polybot-detach-test --no-block /bin/sh -c 'sleep 2; touch /srv/polybot/detached-success'; sleep 60",
                ],
                timeout=1,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pass
        for _ in range(20):
            if (
                docker(
                    "exec",
                    name,
                    "sh",
                    "-c",
                    "test -f /srv/polybot/detached-success && echo done || true",
                )
                == "done"
            ):
                break
            time.sleep(0.25)
        else:
            raise AssertionError("detached systemd operation did not survive SSH loss")

        assert "changed=0" in (directory / "bootstrap-2.log").read_text()
        require_host_security(docker, name, directory, inventory, env, ssh)
        if args.host_only:
            print(
                f"Host bootstrap via {args.initial_access} passed; repeat via polybot changed=0. SSH key rejection/rollback and host security passed; logs: {directory}"
            )
            return
        require_backup_timers(docker, name, enabled=False)
        for enabled in (True, False, True):
            inventory.write_text(
                json.dumps(
                    {
                        "all": {
                            "children": {
                                "polybot": {
                                    "hosts": {
                                        "fixture": backup_variables(
                                            variables, enabled=enabled
                                        )
                                    }
                                }
                            }
                        }
                    }
                )
            )
            with (directory / f"bootstrap-backups-{enabled}.log").open("w") as output:
                subprocess.run(
                    command,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            require_backup_timers(docker, name, enabled=enabled)
        ActivationRehearsal(docker, name, directory, inventory, env).run()
        print(
            docker(
                "exec",
                name,
                "/usr/local/bin/uv",
                "run",
                "--project",
                "/srv/polybot/current",
                "--no-dev",
                "--with",
                "aiosmtpd==1.4.6",
                "python",
                "/srv/polybot/current/rehearsal_mail.py",
                str(DEFAULT_APP_DIRECTORY),
            )
        )
        print(
            "Debian bootstrap without backup inputs twice passed; second pass changed=0. Backup enable/disable/re-enable passed; credentials retained. Tailnet enrollment/Serve require external acceptance."
        )
    finally:
        docker("rm", "-f", name)
        docker("image", "rm", name)


def backup_variables(variables, *, enabled):
    selected = (
        variables
        if enabled
        else {
            key: value
            for key, value in variables.items()
            if not key.startswith("polybot_sftp_") and key != "polybot_age_recipients"
        }
    )
    return selected | {"polybot_backups_enabled": enabled}


def require_host_security(docker, name, directory, inventory, env, ssh):
    denied = subprocess.run(
        [
            *ssh[:-1],
            "-o",
            "BatchMode=yes",
            "-o",
            "ControlPath=none",
            "-o",
            "IdentitiesOnly=yes",
            "root@127.0.0.1",
            "true",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert denied.returncode == 255
    assert "Permission denied" in denied.stderr
    assert "sudo" in docker("exec", name, "id", "-nG", "hec").split()
    assert "Status: active" in docker("exec", name, "ufw", "status")
    assert "sshd" in docker("exec", name, "fail2ban-client", "status", "sshd")
    for unit in ("apt-daily.timer", "apt-daily-upgrade.timer"):
        assert docker("exec", name, "systemctl", "is-enabled", unit) == "enabled"
    assert "HandleLidSwitch=ignore" in docker(
        "exec", name, "cat", "/etc/systemd/logind.conf.d/99-server-lid.conf"
    )

    fixture = directory / "ssh-transaction"
    shutil.copytree(REPOSITORY / "deploy/ansible", fixture)
    play = fixture / "verify.yml"
    play.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Rehearse SSH failures",
                    "hosts": "polybot",
                    "become": True,
                    "gather_facts": False,
                    "vars": {"deployment_contract": deployment_contract()},
                    "tasks": [
                        {"ansible.builtin.import_tasks": "tasks/ssh-hardening.yml"}
                    ],
                }
            ],
            sort_keys=False,
        )
    )
    command = ["ansible-playbook", "-i", str(inventory), str(play)]
    before = docker("exec", name, "sha256sum", SSHD_MAIN_PATH, SSHD_HARDENING_PATH)
    wrong_key = directory / "wrong-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(wrong_key)],
        check=True,
    )
    result = subprocess.run(
        [*command, "-e", f"polybot_ssh_private_key_file={wrong_key}"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (directory / "ssh-wrong-key.log").write_text(result.stdout + result.stderr)
    assert result.returncode != 0 and "failed=1" in result.stdout
    assert "Install the key-only SSH policy" not in result.stdout
    assert (
        docker("exec", name, "sha256sum", SSHD_MAIN_PATH, SSHD_HARDENING_PATH) == before
    )

    backup = "/tmp/sshd-before-rehearsal"
    docker("exec", name, "cp", SSHD_MAIN_PATH, backup)
    try:
        docker(
            "exec",
            name,
            "sh",
            "-c",
            f"printf '\\nMatch User polybot\\n    PasswordAuthentication yes\\n' >> {SSHD_MAIN_PATH}",
        )
        conflicting = docker(
            "exec", name, "sha256sum", SSHD_MAIN_PATH, SSHD_HARDENING_PATH
        )
        result = subprocess.run(
            command, env=env, capture_output=True, text=True, check=False
        )
        (directory / "ssh-policy-rollback.log").write_text(
            result.stdout + result.stderr
        )
        assert result.returncode != 0 and "rescued=1" in result.stdout
        assert "previous configuration was restored" in result.stdout
        assert (
            docker("exec", name, "sha256sum", SSHD_MAIN_PATH, SSHD_HARDENING_PATH)
            == conflicting
        )
    finally:
        docker("exec", name, "cp", backup, SSHD_MAIN_PATH)
        docker("exec", name, "/usr/sbin/sshd", "-t")
        docker("exec", name, "systemctl", "reload", "ssh")


def require_backup_timers(docker, name, *, enabled):
    for unit in BACKUP_TIMER_UNITS:
        assert docker(
            "exec",
            name,
            "systemctl",
            "show",
            unit,
            "--property=UnitFileState",
            "--value",
        ) == ("enabled" if enabled else "disabled")
        assert docker(
            "exec", name, "systemctl", "show", unit, "--property=ActiveState", "--value"
        ) == ("active" if enabled else "inactive")
    assert (
        docker("exec", name, "systemctl", "is-active", MONITOR_TIMER_UNIT) == "active"
    )


if __name__ == "__main__":
    main()
