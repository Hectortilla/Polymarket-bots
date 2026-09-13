"""Prepared-release activation preserves fail-closed recovery and idempotency."""

import fcntl
import hashlib
import json

import pytest
from api.deployment.release import RELEASE_ID_ENV
from api.deployment.services import APPLICATION_SERVICES, DeploymentService

from scripts.beta_release import BetaRelease, activate_bundle
from scripts.compose_project import ComposeProject
from scripts.deployment import state as state_module
from scripts.deployment.attempt import (
    JOURNAL_NAME,
    LOCK_NAME,
    AttemptPhase,
    JournalField,
)
from scripts.deployment.bundle import METADATA_NAME, REQUIRED_FILES
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.images import IMAGE_FIELDS, ImageField, ReleaseImages
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import COMPOSE_FILE, HOST_COMPOSE_NAME, MANIFEST_NAME
from scripts.deployment.state import DeploymentState
from scripts.private_files import write_private


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "host"
    root.mkdir(mode=0o700)
    secrets = root / "secrets"
    secrets.mkdir(mode=0o700)
    for name in [
        "database_url",
        "redis_url",
        "postgres_password",
        "smtp_username",
        "smtp_password",
    ]:
        write_private(secrets / name, b"fixture", mode=0o444)
    write_manifest(
        root / "runtime.env",
        {
            "POLYBOT_AUTH_ORIGIN": "https://host.example.ts.net",
            "POLYBOT_HTTP_PORT": "8081",
            "POLYBOT_SECRETS_DIR": str(secrets),
            "POLYBOT_SMTP_HOST": "smtp.example.com",
            "POLYBOT_SMTP_FROM": "accounts@example.com",
        },
    )
    return root


@pytest.fixture
def bundle(tmp_path):
    return make_bundle(tmp_path / "bundle", "a")


def make_bundle(path, marker):
    path.mkdir()
    values = {
        field: f"ghcr.io/test/image-{index}@sha256:" + str(index) * 64
        for index, field in enumerate(IMAGE_FIELDS, 1)
    }
    values[ImageField.BACKEND] = "ghcr.io/test/backend@sha256:" + marker * 64
    values[RELEASE_ID_ENV] = marker * 40
    for name in REQUIRED_FILES - {"images.env"}:
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            COMPOSE_FILE.read_bytes() if name == "deploy/compose.yaml" else b"fixture"
        )
    write_manifest(path / "images.env", values)
    refresh_bundle(path)
    return path


def refresh_bundle(path):
    images = ReleaseImages.read(path / "images.env")
    (path / METADATA_NAME).write_text(
        json.dumps(
            {
                "tag": "v1.0.0",
                "commit": images.source_commit,
                "files": {
                    name: hashlib.sha256((path / name).read_bytes()).hexdigest()
                    for name in REQUIRED_FILES
                },
            }
        )
    )


@pytest.fixture
def docker(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ComposeProject, "require_local_docker", lambda self: calls.append(("local",))
    )
    monkeypatch.setattr(ComposeProject, "run", lambda self, *args: calls.append(args))
    monkeypatch.setattr(
        BetaRelease, "require_healthy", lambda self: calls.append(("healthy",))
    )
    return calls


def test_fresh_install_pull_migrate_readiness_promote_and_healthy_retry(
    installation, bundle, docker
):
    activate_bundle(installation, bundle)
    assert docker.index(("pull",)) < docker.index(("stop", APPLICATION_SERVICES[0]))
    assert (
        "run",
        "--rm",
        "--no-deps",
        DeploymentService.MIGRATE,
        DeploymentService.MIGRATE,
    ) in docker
    assert docker[-1] == ("healthy",)
    assert (installation / "current").resolve() == bundle
    docker.clear()
    activate_bundle(installation, bundle)
    assert docker == [("local",), ("healthy",)]


@pytest.mark.parametrize("failure", ["pull", "run"])
def test_pull_and_migration_failure_preserve_active_inputs(
    installation, bundle, docker, monkeypatch, tmp_path, failure
):
    activate_bundle(installation, bundle)
    old = (installation / MANIFEST_NAME).read_bytes()
    candidate = make_bundle(tmp_path / "candidate", "b")
    docker.clear()

    def run(self, *args):
        docker.append(args)
        if args[0] == failure:
            raise RuntimeError("injected")

    monkeypatch.setattr(ComposeProject, "run", run)
    with pytest.raises(RuntimeError):
        activate_bundle(installation, candidate)
    assert (installation / MANIFEST_NAME).read_bytes() == old
    assert docker[-1][0] == failure
    assert not any(
        call[0] == "up" and APPLICATION_SERVICES[0] in call for call in docker
    )
    if failure == "pull":
        assert not any(call[0] == "stop" for call in docker)


@pytest.mark.parametrize(
    "failure", ["activation_record", "compose", "manifest", "current"]
)
def test_interrupted_promotion_recovers_without_an_unnecessary_restart(
    installation, bundle, docker, monkeypatch, failure
):
    real_write = state_module.write_private
    real_replace = state_module.os.replace
    failed = False
    activations = []
    monkeypatch.setattr(
        BetaRelease, "activate", lambda self, **kwargs: activations.append(kwargs)
    )

    def write(path, content, **kwargs):
        nonlocal failed
        should_fail = (
            (
                failure == "activation_record"
                and path.name == JOURNAL_NAME
                and json.loads(content)[JournalField.PHASE] == AttemptPhase.ACTIVATED
            )
            or (failure == "compose" and path == installation / HOST_COMPOSE_NAME)
            or (failure == "manifest" and path == installation / MANIFEST_NAME)
        )
        if should_fail and not failed:
            failed = True
            raise OSError("injected")
        real_write(path, content, **kwargs)

    def replace(source, target):
        nonlocal failed
        if failure == "current" and target == installation / "current" and not failed:
            failed = True
            raise OSError("injected")
        real_replace(source, target)

    monkeypatch.setattr(state_module, "write_private", write)
    monkeypatch.setattr(state_module.os, "replace", replace)
    with pytest.raises(OSError):
        activate_bundle(installation, bundle)
    assert DeploymentState(installation).pending()
    activate_bundle(installation, bundle)
    assert len(activations) == (2 if failure == "activation_record" else 1)
    assert DeploymentState(installation).pending() is None
    assert (installation / "current").resolve() == bundle


def test_incompatible_rollback_remains_closed(
    installation, bundle, docker, monkeypatch, tmp_path
):
    activate_bundle(installation, bundle)
    candidate = make_bundle(tmp_path / "candidate", "b")
    docker.clear()

    def run(self, *args):
        docker.append(args)
        if args[-1] == DeploymentService.CHECK:
            raise RuntimeError("schema incompatible")

    monkeypatch.setattr(ComposeProject, "run", run)
    with pytest.raises(RuntimeError):
        activate_bundle(installation, candidate, rollback=True)
    assert docker[-1] == (
        "run",
        "--rm",
        "--no-deps",
        DeploymentService.MIGRATE,
        DeploymentService.CHECK,
    )
    assert DeploymentState(installation).pending().rollback
    with pytest.raises(ValueError, match="operation differs"):
        activate_bundle(installation, candidate)


def test_infrastructure_update_rejected_before_docker(
    installation, bundle, docker, tmp_path
):
    activate_bundle(installation, bundle)
    candidate = make_bundle(tmp_path / "candidate", "b")
    values = ReleaseImages.read(candidate / "images.env").to_values()
    values[ImageField.POSTGRES] = "postgres@sha256:" + "f" * 64
    write_manifest(candidate / "images.env", values)
    refresh_bundle(candidate)
    docker.clear()
    with pytest.raises(ValueError, match="maintenance"):
        activate_bundle(installation, candidate)
    assert not docker


def test_lock_and_private_inputs_fail_before_docker(installation, bundle, docker):
    with (installation / LOCK_NAME).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already running"):
            activate_bundle(installation, bundle)
    (installation / "runtime.env").chmod(0o644)
    with pytest.raises(ValueError, match="mode 600"):
        activate_bundle(installation, bundle)
    assert not docker


@pytest.mark.parametrize(
    "field,value",
    [
        (JournalField.DIRECTORY, "../escape"),
        (JournalField.PHASE, "unknown"),
        (JournalField.ROLLBACK, "false"),
    ],
)
def test_corrupt_journal_blocks_all_mutation(
    installation, bundle, docker, field, value
):
    activate_bundle(installation, bundle)
    state = DeploymentState(installation)
    attempt = state.prepare(
        RuntimeManifest.read(state.manifest),
        state.compose_file.read_bytes(),
        rollback=False,
    )
    record = attempt.to_record()
    record[field] = value
    write_private(state.journal, json.dumps(record).encode())
    docker.clear()
    with pytest.raises(ValueError, match="invalid deployment journal"):
        activate_bundle(installation, bundle)
    assert not docker


def test_explicit_forward_repair_replaces_failed_attempt(
    installation, bundle, docker, monkeypatch, tmp_path
):
    activation = BetaRelease.activate
    monkeypatch.setattr(
        BetaRelease,
        "activate",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failure")),
    )
    with pytest.raises(RuntimeError):
        activate_bundle(installation, bundle)
    repair = make_bundle(tmp_path / "repair", "b")
    monkeypatch.setattr(BetaRelease, "activate", activation)
    activate_bundle(installation, repair)
    assert ReleaseImages.read(installation / MANIFEST_NAME).source_commit == "b" * 40
