"""Real Ansible/systemd activation with disposable Compose processes and local TLS."""

import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from api.auth.config import AUTH_ORIGIN_ENV
from api.deployment.release import RELEASE_ID_ENV
from api.deployment.services import (
    APPLICATION_SERVICES,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)

from control_plane.release_bundle_fixture import worktree_bundle
from scripts.deployment.attempt import JOURNAL_NAME
from scripts.deployment.dotenv import parse_values
from scripts.deployment.images import IMAGE_FIELDS
from scripts.deployment.ingress import IngressMode
from scripts.deployment.paths import (
    CLOUDFLARE_CONFIGURATION_DIRECTORY,
    OPERATIONS_CONFIGURATION_NAME,
    REPOSITORY,
    RUNTIME_CONFIGURATION_NAME,
)
from scripts.deployment.transport_files import HostTransportFile
from scripts.deployment.units import (
    ACTIVATION_SERVICE_UNIT,
    BACKUP_CHECK_SERVICE_UNIT,
    BACKUP_TIMER_UNIT,
    CLOUDFLARE_SERVICE_UNIT,
)


class ReadinessHandler(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(b"fixture readiness")

    def log_message(self, *args):
        pass


class ActivationRehearsal:
    def __init__(
        self,
        docker,
        container: str,
        directory: Path,
        inventory: Path,
        environment: dict,
    ):
        self.docker, self.container, self.directory = docker, container, directory
        self.inventory, self.environment = inventory, environment
        variables = json.loads(inventory.read_text())["all"]["children"]["polybot"][
            "hosts"
        ]["fixture"]
        self.cloudflare = variables.get("polybot_ingress") == IngressMode.CLOUDFLARE

    def run(self) -> None:
        fixture = self.directory / "activation"
        fixture.mkdir()
        shutil.copytree(REPOSITORY / "deploy/ansible", fixture / "ansible")
        certificate, key = fixture / "tls.crt", fixture / "tls.key"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            capture_output=True,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), ReadinessHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Substitute only the unavailable tailnet DNS/TLS boundary; execute
            # the production controller, staging, unit and activation tasks intact.
            tasks_path = fixture / "ansible/tasks/activate.yml"
            tasks = yaml.safe_load(tasks_path.read_text())
            readiness = next(
                task
                for task in next(
                    task["block"]
                    for task in tasks
                    if task.get("name") == "Activate and verify the selected ingress"
                )
                if task.get("name")
                == "Verify HTTPS readiness through the selected ingress"
            )
            readiness["ansible.builtin.uri"]["url"] = (
                f"https://localhost:{server.server_port}/api/v1/health"
            )
            readiness["retries"] = 0
            readiness["ansible.builtin.uri"]["ca_path"] = str(certificate)
            tasks_path.write_text(yaml.safe_dump(tasks, sort_keys=False))
            self.host(
                "systemctl",
                "stop",
                BACKUP_TIMER_UNIT,
                "polybot-backup-check.timer",
                "polybot-monitor.timer",
            )
            self.host("mkdir", "-p", "/srv/polybot/fixture-control")
            # Registry credentials are an external boundary. All Compose commands
            # after this fixture-only login go to the real nested Docker Engine.
            wrapper = fixture / "docker"
            wrapper.write_text(
                '#!/bin/sh\nif [ "$1" = "--config" ] && [ "$3" = "login" ]; then cat >/dev/null; exit 0; fi\nexec /usr/bin/docker "$@"\n'
            )
            self.docker("cp", str(wrapper), self.container + ":/usr/local/bin/docker")
            self.host("chmod", "755", "/usr/local/bin/docker")
            image = json.loads(self.host("/usr/bin/docker", "inspect", "busybox:1.37"))[
                0
            ]["RepoDigests"][0]
            images = {field: image for field in IMAGE_FIELDS}
            bundles = {}
            for index, marker in [(1, "a"), (2, "b")]:
                tag = f"v0.0.{index}"
                output = fixture / f"{tag}.tar.gz"
                worktree_bundle(
                    output,
                    images | {RELEASE_ID_ENV: marker * 40},
                    tag=tag,
                    compose_yaml=self.compose_fixture(),
                    extra_files={
                        "rehearsal_mail.py": (
                            REPOSITORY / "backend/tests/control_plane/mail_rehearsal.py"
                        ).read_bytes()
                    },
                )
                bundles[tag] = output
            # Exercise the wait branch against a real detached oneshot unit.
            unit = fixture / "waiting.service"
            unit.write_text(
                "[Unit]\nDescription=Disposable previous activation\n[Service]\nType=oneshot\nExecStart=/bin/sleep 12\n"
            )
            self.docker(
                "cp",
                str(unit),
                self.container + ":/etc/systemd/system/polybot-activate.service",
            )
            self.host("systemctl", "daemon-reload")
            self.host("systemctl", "start", "--no-block", ACTIVATION_SERVICE_UNIT)
            first = self.play(
                fixture, bundles["v0.0.1"], "v0.0.1", "a", "deploy", "first"
            )
            assert (
                "Wait for a detached activation to finish" in first
                and "failed=0" in first
            )
            assert self.host("readlink", "/srv/polybot/current").endswith("/v0.0.1")
            if self.cloudflare:
                self.require_tunnel_state(active=False)
                self.prepare_public_fixture(fixture)
                self.play(
                    fixture,
                    bundles["v0.0.1"],
                    "v0.0.1",
                    "a",
                    "deploy",
                    "public-opening",
                )
                self.require_tunnel_state(active=True)
            before = self.container_start_timestamp()
            self.play(
                fixture, bundles["v0.0.1"], "v0.0.1", "a", "deploy", "healthy-retry"
            )
            assert self.container_start_timestamp() == before
            self.host("touch", "/srv/polybot/fixture-control/fail")
            self.play(
                fixture,
                bundles["v0.0.2"],
                "v0.0.2",
                "b",
                "deploy",
                "migration-failure",
                success=False,
            )
            assert self.host("readlink", "/srv/polybot/current").endswith("/v0.0.1")
            assert self.host("cat", "/srv/polybot/" + JOURNAL_NAME)
            if self.cloudflare:
                self.require_tunnel_state(active=False)
            self.host("rm", "/srv/polybot/fixture-control/fail")
            self.play(
                fixture, bundles["v0.0.2"], "v0.0.2", "b", "deploy", "forward-retry"
            )
            self.host("touch", "/srv/polybot/fixture-control/fail")
            self.play(
                fixture,
                bundles["v0.0.1"],
                "v0.0.1",
                "a",
                "rollback",
                "rollback-failure",
                success=False,
            )
            assert self.host("readlink", "/srv/polybot/current").endswith("/v0.0.2")
            self.host("rm", "/srv/polybot/fixture-control/fail")
            self.play(
                fixture, bundles["v0.0.1"], "v0.0.1", "a", "rollback", "rollback-retry"
            )
            assert (
                self.host("cat", "/srv/polybot/fixture-control/operation").strip()
                == DeploymentService.CHECK
            )
            conflict = fixture / "conflicting.tar.gz"
            worktree_bundle(
                conflict,
                images | {RELEASE_ID_ENV: "a" * 40},
                tag="v0.0.1",
                compose_yaml=self.compose_fixture(),
                extra_files={"different.txt": b"conflicting immutable asset"},
            )
            self.play(
                fixture,
                conflict,
                "v0.0.1",
                "a",
                "deploy",
                "retained-conflict",
                success=False,
            )
            ReadinessHandler.status = 503
            self.play(
                fixture,
                bundles["v0.0.1"],
                "v0.0.1",
                "a",
                "deploy",
                "https-failure",
                success=False,
            )
            ReadinessHandler.status = 200
            if self.cloudflare:
                self.require_tunnel_state(active=False)
            self.play(
                fixture, bundles["v0.0.1"], "v0.0.1", "a", "deploy", "https-retry"
            )
            if self.cloudflare:
                self.require_tunnel_state(active=True)
            self.host("rm", "/srv/polybot/current")
            result = self.host(
                "sh",
                "-c",
                "systemctl start polybot-backup-check.service >/dev/null 2>&1; systemctl show polybot-backup-check.service --property=Result --value",
            )
            assert result == "exit-code", result
            self.host("ln", "-s", "/srv/polybot/bundles/v0.0.1", "/srv/polybot/current")
            self.host("systemctl", "reset-failed", BACKUP_CHECK_SERVICE_UNIT)
            print(
                "Ansible + installed executor + systemd + Compose deploy/rollback/failure/retry and TLS readiness passed.",
                flush=True,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def host(self, *args):
        return self.docker("exec", self.container, *args)

    def prepare_public_fixture(self, fixture):
        # Substitute only the external Cloudflare connection. The production unit
        # still reads its protected token as the dedicated service account.
        override = fixture / "connector.conf"
        token_path = (
            CLOUDFLARE_CONFIGURATION_DIRECTORY / HostTransportFile.CLOUDFLARE_TOKEN
        )
        override.write_text(
            "[Service]\nExecStart=\n"
            f"ExecStart=/bin/sh -c 'test -s {token_path} && exec /bin/sleep infinity'\n"
        )
        drop_in = f"/etc/systemd/system/{CLOUDFLARE_SERVICE_UNIT}.d"
        self.host("mkdir", "-p", drop_in)
        self.docker(
            "cp", str(override), self.container + ":" + drop_in + "/fixture.conf"
        )
        self.host("systemctl", "daemon-reload")
        record = json.loads(self.inventory.read_text())
        variables = record["all"]["children"]["polybot"]["hosts"]["fixture"]
        variables["polybot_public_enabled"] = True
        self.inventory.write_text(json.dumps(record))
        root = variables["polybot_root"]
        runtime = parse_values(self.host("cat", f"{root}/{RUNTIME_CONFIGURATION_NAME}"))
        runtime[AUTH_ORIGIN_ENV] = variables["polybot_origin"]
        operations = json.loads(
            self.host("cat", f"{root}/{OPERATIONS_CONFIGURATION_NAME}")
        )
        operations["public_enabled"] = True
        for name, content in (
            (
                RUNTIME_CONFIGURATION_NAME,
                "\n".join(
                    f"{key}={json.dumps(value)}" for key, value in runtime.items()
                )
                + "\n",
            ),
            (OPERATIONS_CONFIGURATION_NAME, json.dumps(operations)),
        ):
            path = fixture / name
            path.write_text(content)
            self.docker("cp", str(path), self.container + f":{root}/{name}")
            self.host("chown", "polybot:polybot", f"{root}/{name}")
            self.host("chmod", "600", f"{root}/{name}")

    def require_tunnel_state(self, *, active):
        state = self.host(
            "systemctl",
            "show",
            CLOUDFLARE_SERVICE_UNIT,
            "--property=ActiveState",
            "--value",
        )
        assert state == ("active" if active else "inactive"), state
        enabled = self.host(
            "systemctl",
            "show",
            CLOUDFLARE_SERVICE_UNIT,
            "--property=UnitFileState",
            "--value",
        )
        assert enabled == ("enabled" if active else "disabled"), enabled

    def container_start_timestamp(self):
        return self.host(
            "docker", "inspect", "--format", "{{.State.StartedAt}}", "polybot-api-1"
        )

    def play(self, fixture, bundle, tag, marker, operation, label, *, success=True):
        inputs = fixture / "inputs.json"
        inputs.write_text(
            json.dumps(
                {
                    "release_bundle": str(bundle),
                    "release_tag": tag,
                    "release_commit": marker * 40,
                    "registry_username": "fixture",
                    "registry_token": "fixture",
                }
            )
        )
        inputs.chmod(0o600)
        result = subprocess.run(
            [
                "ansible-playbook",
                "-i",
                str(self.inventory),
                str(fixture / "ansible" / f"{operation}.yml"),
                "-e",
                "@" + str(inputs),
            ],
            env=self.environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        (fixture / f"{label}.log").write_text(result.stdout)
        if (result.returncode == 0) != success:
            raise AssertionError(
                f"Unexpected {label} outcome; inspect {fixture / (label + '.log')}"
            )
        return result.stdout

    @staticmethod
    def compose_fixture() -> bytes:
        services = {}
        for service in (*APPLICATION_SERVICES, POSTGRES_SERVICE, REDIS_SERVICE):
            services[str(service)] = {
                "image": "${POLYBOT_BACKEND_IMAGE}",
                "command": ["sh", "-c", "sleep 86400"],
            }
            if service not in {DeploymentService.WORKER, DeploymentService.RECOVERY}:
                services[str(service)]["healthcheck"] = {
                    "test": ["CMD", "true"],
                    "interval": "1s",
                    "timeout": "1s",
                    "retries": 3,
                }
        services[DeploymentService.MIGRATE.value] = {
            "image": "${POLYBOT_BACKEND_IMAGE}",
            "entrypoint": [
                "sh",
                "-c",
                'test ! -f /control/fail || exit 1; echo "$0" >/control/operation',
            ],
            "volumes": ["/srv/polybot/fixture-control:/control"],
        }
        return yaml.safe_dump({"services": services}).encode()
