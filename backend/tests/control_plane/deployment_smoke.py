"""Disposable HTTPS Compose acceptance; never targets an existing deployment."""

import json
import secrets
import ssl
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx

from api.auth.policy import LOGIN_PATH, LOGOUT_PATH, REGISTER_PATH
from api.catalog.definitions import NODE_BASED_DEFINITION_ID
from api.catalog.graphs.starter import STARTER_NODE_GRAPH
from api.deployment.settings import DEFAULT_LEASE_SECONDS, DEFAULT_WORKER_CONCURRENCY
from api.http.routes.events import LAST_EVENT_ID_HEADER
from api.http.routes.paths import (
    BOTS_PATH,
    BOT_PATH,
    BOT_RUNS_PATH,
    GRAPH_TEMPLATES_PATH,
    HEALTH_PATH,
    RUN_EVENTS_PATH,
    RUN_EVENTS_STREAM_PATH,
    RUN_PATH,
    RUN_STOP_PATH,
    api_route_path,
)
from api.runs.status import RunStatus
from scripts.beta_release import BetaRelease, COMPOSE_FILE, REPOSITORY

STAGING_ORIGIN = "https://localhost:8443"
TEST_PASSWORD = "disposable staging password 123"


class DeploymentSmoke:
    def __init__(self) -> None:
        self.identifier = uuid4().hex[:12]
        self.project = f"polybot-beta-test-{self.identifier}"
        self.directory = REPOSITORY / "data" / "beta" / self.project
        self.directory.mkdir(parents=True, mode=0o700)
        self.manifest = self.directory / "release.env"
        self.values: dict[str, str] = {}
        self.sensitive_values = {TEST_PASSWORD}

    def run(self) -> None:
        try:
            self.prepare()
            release = BetaRelease(self.manifest, self.project)
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
            if self.manifest.exists():
                self.compose("down", "--volumes", "--remove-orphans")

    def prepare(self) -> None:
        directory = self.directory / "secrets"
        directory.mkdir(mode=0o700)
        password = secrets.token_urlsafe(32)
        self.sensitive_values.add(password)
        for name, value in {
            "postgres_password": password,
            "database_url": f"postgresql://polybot:{password}@postgres:5432/polybot",
            "redis_url": "redis://redis:6379/0",
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
                f"deploy/{surface}.Dockerfile",
                "-t",
                f"{self.project}-{surface}",
                ".",
            )
        for tag in ("postgres:17", "redis:7-alpine"):
            self.command("docker", "pull", tag)
        self.values = {
            "POLYBOT_RELEASE_ID": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "POLYBOT_AUTH_ORIGIN": STAGING_ORIGIN,
            "POLYBOT_HTTPS_PORT": "8443",
            "POLYBOT_SECRETS_DIR": str(directory),
        }
        for surface, tag in {
            "BACKEND": f"{self.project}-backend",
            "FRONTEND": f"{self.project}-frontend",
            "POSTGRES": "postgres:17",
            "REDIS": "redis:7-alpine",
        }.items():
            self.values[f"POLYBOT_{surface}_IMAGE"] = self.image_id(tag)
        self.write_manifest()

    def failed_migration_stays_closed(self, release: BetaRelease) -> None:
        path = Path(self.values["POLYBOT_SECRETS_DIR"]) / "database_url"
        original = path.read_text()
        try:
            path.write_text("postgresql://polybot:invalid@postgres:5432/polybot")
            try:
                release.activate(rollback=False)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("failed migration activated a release")
            running = set(
                self.compose("ps", "--status", "running", "--services").splitlines()
            )
            assert not running.intersection({"entrypoint", "api", "worker"})
        finally:
            path.write_text(original)
        release.activate(rollback=False)
        self.require_health()

    def install_runtime_fixture(self) -> None:
        self.compose("stop", "entrypoint", "api", "worker")
        tag = f"{self.project}-acceptance"
        self.command(
            "docker",
            "build",
            "--build-arg",
            f"BACKEND_IMAGE={self.project}-backend",
            "-f",
            "deploy/acceptance.Dockerfile",
            "-t",
            tag,
            ".",
        )
        self.values["POLYBOT_BACKEND_IMAGE"] = self.image_id(tag)
        self.write_manifest()
        self.compose("up", "-d", "--no-deps", "--wait", "api", "worker", fixture=True)
        self.compose("up", "-d", "--no-deps", "--wait", "entrypoint", fixture=True)
        self.require_health()

    def exercise_runs(self) -> None:
        with self.client() as first, self.client() as second:
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
                client.post(api_route_path(LOGOUT_PATH), json={}).raise_for_status()
                login = client.post(api_route_path(LOGIN_PATH), json=credentials)
                login.raise_for_status()
                self.sensitive_values.update(login.cookies.values())
            template = first.post(
                api_route_path(GRAPH_TEMPLATES_PATH),
                json={
                    "name": "TLS acceptance graph",
                    "graph": STARTER_NODE_GRAPH.model_dump(mode="json"),
                },
            )
            template.raise_for_status()
            response = first.post(
                api_route_path(BOTS_PATH),
                json={
                    "definition_id": NODE_BASED_DEFINITION_ID,
                    "graph_template_id": template.json()["id"],
                    "inputs": {
                        "name": "TLS acceptance",
                        "market_slugs": ["browser-market"],
                    },
                },
            )
            response.raise_for_status()
            bot_id = response.json()["id"]
            assert (
                second.get(api_route_path(BOT_PATH, bot_id=bot_id)).status_code == 404
            )
            runs = []
            for _ in range(DEFAULT_WORKER_CONCURRENCY + 1):
                result = first.post(
                    api_route_path(BOT_RUNS_PATH, bot_id=bot_id), json={}
                )
                result.raise_for_status()
                runs.append(result.json()["id"])
            self.wait_for(
                lambda: sum(
                    self.run_status(first, run_id) == RunStatus.RUNNING
                    for run_id in runs
                )
                == DEFAULT_WORKER_CONCURRENCY
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
                second.get(api_route_path(RUN_PATH, run_id=active)).status_code == 404
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
            with first.stream(
                "GET", stream_path, headers={LAST_EVENT_ID_HEADER: str(event["id"])}
            ) as stream:
                stream.raise_for_status()
                first.post(
                    api_route_path(RUN_STOP_PATH, run_id=active), json={}
                ).raise_for_status()
                terminal = next(
                    json.loads(line.removeprefix("data:"))
                    for line in stream.iter_lines()
                    if line.startswith("data:")
                )
                assert terminal["id"] > event["id"]
                assert terminal["payload"]["status"] == RunStatus.STOPPED
            self.wait_for(lambda: self.run_status(first, active) == RunStatus.STOPPED)
            lost = next(run_id for run_id in runs if run_id not in {queued, active})
            self.compose("stop", "--timeout", "0", "worker", fixture=True)
            time.sleep(DEFAULT_LEASE_SECONDS + 1)
            self.compose(
                "run", "--rm", "--no-deps", "worker", "reconcile", lost, fixture=True
            )
            assert self.run_status(first, lost) == RunStatus.INTERRUPTED
            assert (
                first.get(api_route_path(RUN_EVENTS_PATH, run_id=lost)).json()[
                    "events"
                ][-1]["payload"]["status"]
                == RunStatus.INTERRUPTED
            )

    def require_private_ports(self) -> None:
        entries = [
            json.loads(line)
            for line in self.compose("ps", "--format", "json").splitlines()
        ]
        for entry in entries:
            for port in entry.get("Publishers") or []:
                if port.get("PublishedPort"):
                    assert (
                        entry["Service"] == "entrypoint" and port["URL"] == "127.0.0.1"
                    )

    def require_health(self) -> None:
        def healthy():
            try:
                with self.client() as client:
                    return client.get(api_route_path(HEALTH_PATH)).status_code == 200
            except httpx.TransportError:
                return False

        self.wait_for(healthy)

    def client(self):
        certificate = Path(self.values["POLYBOT_SECRETS_DIR"]) / "tls_cert"
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
                ["-f", str(REPOSITORY / "deploy" / "acceptance.compose.yaml")]
            )
        return self.command(*command, *arguments)

    def write_manifest(self):
        self.manifest.write_text(
            "\n".join(f"{key}={value}" for key, value in self.values.items())
        )

    def command(self, *arguments: str) -> str:
        result = subprocess.run(
            arguments,
            cwd=REPOSITORY,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        with (self.directory / "commands.log").open("a") as log:
            if any(value in result.stdout for value in self.sensitive_values):
                raise AssertionError(
                    "a deployment command exposed an acceptance credential"
                )
            log.write(result.stdout)
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
            if predicate():
                return
            time.sleep(1)
        raise AssertionError("staging condition did not converge within 90 seconds")


if __name__ == "__main__":
    DeploymentSmoke().run()
