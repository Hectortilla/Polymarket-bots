"""Disposable HTTPS Compose acceptance; never targets an existing deployment."""

import json
import secrets
import shutil
import ssl
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
from api.auth.config import AUTH_ORIGIN_ENV
from api.auth.mail.config import SMTP_FROM_ENV, SMTP_HOST_ENV
from api.auth.policy import LOGIN_PATH, LOGOUT_PATH, REGISTER_PATH
from api.auth.recovery.policy import VERIFY_COMPLETE_PATH, VERIFY_REQUEST_PATH
from api.catalog.definitions import NODE_BASED_DEFINITION_ID
from api.catalog.graphs.starter import STARTER_NODE_GRAPH
from api.deployment.release import RELEASE_ID_ENV
from api.deployment.services import (
    APPLICATION_SERVICES,
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)
from api.execution.policy import WORKER_STOP_GRACE_SECONDS
from api.execution.recovery.policy import DELIVERY_RETRY_SECONDS
from api.http.routes.events import LAST_EVENT_ID_HEADER
from api.http.routes.paths import (
    BOT_PATH,
    BOT_RUNS_PATH,
    BOTS_PATH,
    HEALTH_PATH,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    api_route_path,
)
from api.limits.policy import PAPER_BETA
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS
from api.runs.status import RunStatus
from fastapi import status

from control_plane.account_mail_fixture import (
    MAILBOX_EMAIL_PARAMETER,
    MAILBOX_LINK_FIELD,
    MAILBOX_PATH,
)
from control_plane.browser_limits_fixture import CLEAR_LIMITS_PATH
from scripts.beta_release import BetaRelease
from scripts.deployment.dotenv import read_values
from scripts.deployment.images import ImageField
from scripts.deployment.paths import (
    COMPOSE_FILE,
    REPOSITORY,
    SECRETS_DIRECTORY_NAME,
    SOURCE_DEPLOY_DIRECTORY,
)
from scripts.deployment.runtime_contracts import (
    DEFAULT_AUTH_ORIGIN,
    DEFAULT_HTTP_PORT,
    HTTP_PORT_ENV,
    SECRETS_DIRECTORY_ENV,
)
from scripts.deployment.storage import SecretFile, database_url, redis_url
from scripts.local_docker import LocalDocker

STAGING_ORIGIN = DEFAULT_AUTH_ORIGIN
INFRASTRUCTURE = read_values(REPOSITORY / "deploy/infrastructure.env")
DEFAULT_POSTGRES_IMAGE = INFRASTRUCTURE[ImageField.POSTGRES]
DEFAULT_REDIS_IMAGE = INFRASTRUCTURE[ImageField.REDIS]
TEST_PASSWORD = "disposable staging password 123"


class DeploymentSmoke:
    def __init__(self) -> None:
        self.docker = LocalDocker.from_context()
        self.identifier = uuid4().hex[:12]
        self.project = f"polybot-beta-test-{self.identifier}"
        self.directory = REPOSITORY / "data" / "beta" / self.project
        self.directory.mkdir(parents=True, mode=0o700)
        self.manifest = self.directory / "release.env"
        self.values: dict[str, str] = {}
        self.sensitive_values = {TEST_PASSWORD}
        self.tls_process = None

    def run(self) -> None:
        try:
            self.prepare()
            release = BetaRelease.from_manifest(self.manifest, self.project)
            release.activate(rollback=False)
            self.require_health()
            release.activate(rollback=True)
            self.require_health()
            self.require_private_ports()
            self.failed_migration_stays_closed(release)
            self.install_runtime_fixture()
            self.command(
                "npm",
                "--prefix",
                "frontend",
                "exec",
                "--",
                "playwright",
                "test",
                "--config=frontend/playwright.deployment.config.ts",
            )
            self.verify_proxy_boundary()
            self.exercise_runs()
            self.compose("logs", "--no-color")
            print(
                "HTTPS, ownership, queueing, Stop, reload/SSE, worker loss, release and rollback passed.",
                flush=True,
            )
        except Exception:
            if self.manifest.exists():
                self.compose("logs", "--tail", "100")
            raise
        finally:
            self.stop_tls()
            if self.manifest.exists():
                self.compose("down", "--volumes", "--remove-orphans")

    def prepare(self) -> None:
        directory = self.directory / SECRETS_DIRECTORY_NAME
        directory.mkdir(mode=0o700)
        password = secrets.token_urlsafe(32)
        self.sensitive_values.add(password)
        for name, value in {
            SecretFile.POSTGRES_PASSWORD: password,
            SecretFile.DATABASE_URL: database_url(password),
            SecretFile.REDIS_URL: redis_url(),
            SecretFile.SMTP_USERNAME: "acceptance-user",
            SecretFile.SMTP_PASSWORD: "acceptance-password",
        }.items():
            (directory / name).write_text(value)
            (directory / name).chmod(0o644)
        self.command(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(directory / "tls_key"),
            "-out",
            str(directory / "tls_cert"),
            "-days",
            "2",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        )
        for surface in ("backend", "frontend"):
            self.command(
                "docker",
                "build",
                "-f",
                str(SOURCE_DEPLOY_DIRECTORY / f"{surface}.Dockerfile"),
                "-t",
                f"{self.project}-{surface}",
                ".",
            )
        for tag in (DEFAULT_POSTGRES_IMAGE, DEFAULT_REDIS_IMAGE):
            self.command("docker", "pull", tag)
        self.values = {
            RELEASE_ID_ENV: subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            AUTH_ORIGIN_ENV: STAGING_ORIGIN,
            SMTP_HOST_ENV: "smtp.invalid",
            SMTP_FROM_ENV: "accounts@example.com",
            HTTP_PORT_ENV: str(DEFAULT_HTTP_PORT),
            SECRETS_DIRECTORY_ENV: str(directory),
        }
        for surface, tag in {
            ImageField.BACKEND: f"{self.project}-backend",
            ImageField.FRONTEND: f"{self.project}-frontend",
            ImageField.POSTGRES: DEFAULT_POSTGRES_IMAGE,
            ImageField.REDIS: DEFAULT_REDIS_IMAGE,
        }.items():
            self.values[surface] = self.image_id(tag)
        self.write_manifest()
        # A separate loopback TLS terminator exercises the production HTTP Caddy path.
        binary = shutil.which("caddy")
        if binary is None:
            container = self.project + "-caddy-binary"
            self.command("docker", "create", "--name", container, "caddy:2.11-alpine")
            binary = str(self.directory / "caddy")
            try:
                self.command("docker", "cp", container + ":/usr/bin/caddy", binary)
            finally:
                self.command("docker", "rm", container)
        config = self.directory / "TLS.Caddyfile"
        config.write_text(
            (REPOSITORY / "deploy/acceptance-tls.Caddyfile")
            .read_text()
            .replace("/tls/", str(directory) + "/")
        )
        self.tls_process = subprocess.Popen(
            [binary, "run", "--config", str(config), "--adapter", "caddyfile"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_tls(self):
        if self.tls_process:
            self.tls_process.terminate()
            self.tls_process.wait(timeout=10)

    def failed_migration_stays_closed(self, release: BetaRelease) -> None:
        path = Path(self.values[SECRETS_DIRECTORY_ENV]) / SecretFile.DATABASE_URL
        original = path.read_text()
        try:
            path.write_text(database_url("invalid"))
            try:
                release.activate(rollback=False)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("failed migration activated a release")
            running = set(
                self.compose("ps", "--status", "running", "--services").splitlines()
            )
            assert not running.intersection(set(APPLICATION_SERVICES))
        finally:
            path.write_text(original)
        release.activate(rollback=False)
        self.require_health()

    def install_runtime_fixture(self) -> None:
        self.compose("stop", *APPLICATION_SERVICES)
        tag = f"{self.project}-acceptance"
        self.command(
            "docker",
            "build",
            "--build-arg",
            f"BACKEND_IMAGE={self.project}-backend",
            "-f",
            str(SOURCE_DEPLOY_DIRECTORY / "acceptance.Dockerfile"),
            "-t",
            tag,
            ".",
        )
        self.values[ImageField.BACKEND] = self.image_id(tag)
        self.write_manifest()
        self.compose(
            "up", "-d", "--no-deps", "--wait", *APPLICATION_SERVICES[1:], fixture=True
        )
        self.compose(
            "up", "-d", "--no-deps", "--wait", ENTRYPOINT_SERVICE, fixture=True
        )
        self.require_health()

    def verify_proxy_boundary(self):
        with self.client() as client:
            observation = client.get(
                "/api/v1/_fixture/proxy",
                headers={
                    "X-Forwarded-For": "203.0.113.9",
                    "Forwarded": "for=203.0.113.9",
                    "X-Forwarded-Proto": "http",
                    "Tailscale-User-Login": "spoof@example.com",
                },
            ).json()
            assert observation == {
                "client": "127.0.0.1",
                "scheme": "https",
                "forwarded": None,
                "identity": None,
            }
            response = client.post(
                api_route_path(LOGOUT_PATH),
                json={},
                headers={"Origin": "https://spoof.example"},
            )
            assert response.status_code == status.HTTP_403_FORBIDDEN
        output = self.command(
            "docker",
            "run",
            "--rm",
            "--network",
            self.project + "_edge",
            "--entrypoint",
            "python",
            self.values[ImageField.BACKEND],
            "-c",
            "import json,urllib.request; request=urllib.request.Request('http://entrypoint:8081/api/v1/_fixture/proxy',headers={'X-Forwarded-For':'203.0.113.9','Forwarded':'for=203.0.113.9'}); print(urllib.request.urlopen(request).read().decode())",
        )
        assert json.loads(output)["client"] != "203.0.113.9"

    def exercise_runs(self) -> None:
        with self.client() as first, self.client() as second:
            first.post(CLEAR_LIMITS_PATH).raise_for_status()
            for client, suffix in ((first, "first"), (second, "second")):
                credentials = {
                    "email": f"{suffix}-{self.identifier}@example.com",
                    "password": TEST_PASSWORD,
                }
                response = client.post(api_route_path(REGISTER_PATH), json=credentials)
                response.raise_for_status()
                self.sensitive_values.update(response.cookies.values())
                cookie = response.headers["set-cookie"].lower()
                assert "secure" in cookie and "httponly" in cookie
                client.post(
                    api_route_path(VERIFY_REQUEST_PATH),
                    json={"email": credentials["email"]},
                ).raise_for_status()
                link = client.get(
                    MAILBOX_PATH,
                    params={MAILBOX_EMAIL_PARAMETER: credentials["email"]},
                ).json()[MAILBOX_LINK_FIELD]
                assert link.startswith(STAGING_ORIGIN + "/")
                token = link.split("#")[1]
                self.sensitive_values.add(token)
                client.post(
                    api_route_path(VERIFY_COMPLETE_PATH),
                    json={"token": token, "new_password": TEST_PASSWORD},
                ).raise_for_status()
                client.post(api_route_path(LOGOUT_PATH), json={}).raise_for_status()
                login = client.post(api_route_path(LOGIN_PATH), json=credentials)
                login.raise_for_status()
                self.sensitive_values.update(login.cookies.values())
            response = first.post(
                api_route_path(BOTS_PATH),
                json={
                    "definition_id": NODE_BASED_DEFINITION_ID,
                    "graph": STARTER_NODE_GRAPH.model_dump(mode="json"),
                    "inputs": {
                        "name": "TLS acceptance",
                        "market_slugs": ["browser-market"],
                    },
                },
            )
            response.raise_for_status()
            bot_id = response.json()["id"]
            assert (
                second.get(api_route_path(BOT_PATH, bot_id=bot_id)).status_code
                == status.HTTP_404_NOT_FOUND
            )
            runs = []
            for _ in range(PAPER_BETA.active_runs + 1):
                result = first.post(
                    api_route_path(BOT_RUNS_PATH, bot_id=bot_id), json={}
                )
                result.raise_for_status()
                runs.append(result.json()["id"])
                if len(runs) <= PAPER_BETA.active_runs:
                    self.wait_for(
                        lambda: self.run_status(first, runs[-1]) == RunStatus.RUNNING
                    )
            self.wait_for(
                lambda: (
                    sum(
                        self.run_status(first, run_id) == RunStatus.RUNNING
                        for run_id in runs
                    )
                    == PAPER_BETA.active_runs
                )
            )
            queued = next(
                run_id
                for run_id in runs
                if self.run_status(first, run_id) == RunStatus.QUEUED
            )
            first.post(
                api_route_path(RUN_STOP_PATH, run_id=queued), json={}
            ).raise_for_status()
            assert self.run_status(first, queued) == RunStatus.STOPPED
            active = next(run_id for run_id in runs if run_id != queued)
            assert (
                second.get(api_route_path(RUN_PATH, run_id=active)).status_code
                == status.HTTP_404_NOT_FOUND
            )
            # Repeated independent HTTP requests reach the shared database through
            # the multi-worker proxy and restore committed progress.
            events_path = api_route_path(RUN_EVENTS_PATH, run_id=active)
            self.wait_for(lambda: bool(first.get(events_path).json()["events"]))
            for _ in range(4):
                first.get(events_path).raise_for_status()
            stream_path = api_route_path(RUN_EVENTS_STREAM_PATH, run_id=active)
            with first.stream("GET", stream_path) as stream:
                stream.raise_for_status()
                event = next(
                    json.loads(line.removeprefix("data:"))
                    for line in stream.iter_lines()
                    if line.startswith("data:")
                )
            first.post(
                api_route_path(RUN_STOP_PATH, run_id=active), json={}
            ).raise_for_status()
            self.wait_for(lambda: self.run_status(first, active) == RunStatus.STOPPED)
            with first.stream(
                "GET", stream_path, headers={LAST_EVENT_ID_HEADER: str(event["id"])}
            ) as stream:
                stream.raise_for_status()
                terminal = next(
                    json.loads(line.removeprefix("data:"))
                    for line in stream.iter_lines()
                    if line.startswith("data:")
                )
                assert terminal["id"] > event["id"]
                assert terminal["payload"]["status"] == RunStatus.STOPPED
            self.wait_for(lambda: self.run_status(first, active) == RunStatus.STOPPED)
            result = first.post(api_route_path(BOT_RUNS_PATH, bot_id=bot_id), json={})
            result.raise_for_status()
            lost = result.json()["id"]
            self.wait_for(lambda: self.run_status(first, lost) == RunStatus.RUNNING)
            self.compose("stop", POSTGRES_SERVICE, fixture=True)
            self.compose(
                "stop", "--timeout", "0", DeploymentService.WORKER, fixture=True
            )
            time.sleep(DEFAULT_LEASE_SECONDS + DELIVERY_RETRY_SECONDS)
            self.compose(
                "up", "-d", "--no-deps", "--wait", POSTGRES_SERVICE, fixture=True
            )
            self.wait_for(lambda: self.run_status(first, lost) == RunStatus.INTERRUPTED)
            assert (
                first.get(api_route_path(RUN_EVENTS_PATH, run_id=lost)).json()[
                    "events"
                ][-1]["payload"]["status"]
                == RunStatus.INTERRUPTED
            )

            # A queued obligation survives Redis loss and a missing worker.
            result = first.post(api_route_path(BOT_RUNS_PATH, bot_id=bot_id), json={})
            result.raise_for_status()
            stranded = result.json()["id"]
            self.compose("stop", REDIS_SERVICE, fixture=True)
            time.sleep(DELIVERY_RETRY_SECONDS * 2)
            self.compose(
                "up",
                "-d",
                "--no-deps",
                "--wait",
                REDIS_SERVICE,
                DeploymentService.WORKER,
                fixture=True,
            )
            self.wait_for(lambda: self.run_status(first, stranded) == RunStatus.RUNNING)
            shutdown_started = time.monotonic()
            self.compose("stop", DeploymentService.WORKER, fixture=True)
            assert time.monotonic() - shutdown_started < WORKER_STOP_GRACE_SECONDS + 5
            self.wait_for(
                lambda: self.run_status(first, stranded) == RunStatus.INTERRUPTED
            )
            history = first.get(
                api_route_path(RUN_EVENTS_PATH, run_id=stranded)
            ).json()["events"]
            terminal_events = [
                event
                for event in history
                if event["payload"].get("status") == RunStatus.INTERRUPTED
            ]
            assert len(terminal_events) == 1

    def require_private_ports(self) -> None:
        entries = [
            json.loads(line)
            for line in self.compose("ps", "--format", "json").splitlines()
        ]
        for entry in entries:
            for port in entry.get("Publishers") or []:
                if port.get("PublishedPort"):
                    assert (
                        entry["Service"] == ENTRYPOINT_SERVICE
                        and port["URL"] == "127.0.0.1"
                    )

    def require_health(self) -> None:
        def healthy():
            try:
                with self.client() as client:
                    return (
                        client.get(api_route_path(HEALTH_PATH)).status_code
                        == status.HTTP_200_OK
                    )
            except httpx.TransportError:
                return False

        self.wait_for(healthy)

    def client(self):
        certificate = Path(self.values[SECRETS_DIRECTORY_ENV]) / "tls_cert"
        return httpx.Client(
            base_url=STAGING_ORIGIN,
            verify=ssl.create_default_context(cafile=str(certificate)),
            headers={"Origin": STAGING_ORIGIN},
            timeout=15,
        )

    def compose(self, *arguments: str, fixture: bool = False) -> str:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--env-file",
            str(self.manifest),
            "-f",
            str(COMPOSE_FILE),
        ]
        if fixture:
            command.extend(
                [
                    "-f",
                    str(
                        REPOSITORY / SOURCE_DEPLOY_DIRECTORY / "acceptance.compose.yaml"
                    ),
                ]
            )
        return self.command(*command, *arguments)

    def write_manifest(self):
        self.manifest.write_text(
            "\n".join(f"{key}={value}" for key, value in self.values.items())
        )

    def command(self, *arguments: str) -> str:
        if arguments and arguments[0] == "docker":
            if arguments[1:2] == ("--host",):
                if arguments[2] != self.docker.endpoint:
                    raise ValueError(
                        "rehearsal Docker endpoint differs from its local context"
                    )
            else:
                arguments = tuple(self.docker.command(*arguments[1:]))
        result = subprocess.run(
            arguments,
            cwd=REPOSITORY,
            env=self.docker.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        with (self.directory / "commands.log").open("a") as log:
            if any(value in result.stdout for value in self.sensitive_values):
                raise AssertionError(
                    "a deployment command exposed an acceptance credential"
                )
            log.write(result.stdout)
        if result.returncode:
            print(result.stdout, end="", flush=True)
        result.check_returncode()
        return result.stdout

    @staticmethod
    def run_status(client, run_id):
        response = client.get(api_route_path(RUN_PATH, run_id=run_id))
        response.raise_for_status()
        return response.json()["status"]

    @staticmethod
    def image_id(tag):
        return subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag], text=True
        ).strip()

    @staticmethod
    def wait_for(predicate):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise AssertionError("staging condition did not converge within 90 seconds")


if __name__ == "__main__":
    DeploymentSmoke().run()
