"""Two-pass preparation on an isolated Debian systemd container, no tailnet account."""

import json
import os
import subprocess
import time
from uuid import uuid4

from control_plane.activation_rehearsal import ActivationRehearsal
from scripts.deployment.inventory import SUPPORTED_ARCHITECTURES
from scripts.deployment.paths import DEFAULT_APP_DIRECTORY, REPOSITORY
from scripts.deployment.runtime_contracts import DEFAULT_HTTP_PORT
from scripts.deployment.units import BACKUP_TIMER_UNIT
from scripts.local_docker import LocalDocker


def main():
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
        inventory = directory / "inventory.json"
        inventory.write_text(
            json.dumps(
                {"all": {"children": {"polybot": {"hosts": {"fixture": variables}}}}}
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
            "root@127.0.0.1",
        ]
        try:
            subprocess.run(
                [
                    *ssh,
                    "systemd-run --unit=polybot-detach-test --no-block /bin/sh -c 'sleep 2; touch /srv/polybot/detached-success'; sleep 60",
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
        assert (
            docker("exec", name, "systemctl", "is-enabled", BACKUP_TIMER_UNIT)
            == "enabled"
        )
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
            "Debian bootstrap twice passed; credentials retained and second pass changed=0. Tailnet enrollment/Serve require external acceptance."
        )
    finally:
        docker("rm", "-f", name)
        docker("image", "rm", name)


if __name__ == "__main__":
    main()
