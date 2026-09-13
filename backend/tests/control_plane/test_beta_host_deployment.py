"""Prepared-release activation preserves fail-closed recovery and idempotency."""

import fcntl
import json
import re

import pytest
from api.deployment.services import APPLICATION_SERVICES, DeploymentService

from control_plane.beta_host_fixture import make_bundle, refresh_bundle
from scripts.beta_release import BetaRelease
from scripts.beta_release.activation import DeploymentActivator
from scripts.compose_project import ComposeProject
from scripts.deployment import state as state_module
from scripts.deployment.attempt import (
    INVALID_JOURNAL_MESSAGE,
    JOURNAL_NAME,
    LOCK_NAME,
    AttemptPhase,
    JournalField,
)
from scripts.deployment.bundle.contracts import (
    RELEASE_IMAGE_MANIFEST_FILENAME,
)
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.images import ImageField, ReleaseImages
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import (
    CURRENT_RELEASE_NAME,
    HOST_COMPOSE_NAME,
    MANIFEST_NAME,
    RELEASES_DIRECTORY_NAME,
    RUNTIME_CONFIGURATION_NAME,
)
from scripts.deployment.state import DeploymentState
from scripts.private_files import write_private


def test_fresh_install_pull_migrate_readiness_promote_and_healthy_retry(
    installation, bundle, compose_calls
):
    DeploymentActivator(installation).activate(bundle)
    assert compose_calls.index(("pull",)) < compose_calls.index(
        ("stop", APPLICATION_SERVICES[0])
    )
    assert (
        "run",
        "--rm",
        "--no-deps",
        DeploymentService.MIGRATE,
        DeploymentService.MIGRATE,
    ) in compose_calls
    assert compose_calls[-1] == ("healthy",)
    assert (installation / CURRENT_RELEASE_NAME).resolve() == bundle
    compose_calls.clear()
    DeploymentActivator(installation).activate(bundle)
    assert compose_calls == [("local",), ("healthy",)]


@pytest.mark.parametrize("failure", ["pull", "run"])
def test_pull_and_migration_failure_preserve_active_inputs(
    installation, bundle, compose_calls, monkeypatch, tmp_path, failure
):
    DeploymentActivator(installation).activate(bundle)
    old = (installation / MANIFEST_NAME).read_bytes()
    candidate = make_bundle(installation / RELEASES_DIRECTORY_NAME / "candidate", "b")
    compose_calls.clear()

    def run(self, *args):
        compose_calls.append(args)
        if args[0] == failure:
            raise RuntimeError("injected")

    monkeypatch.setattr(ComposeProject, "run", run)
    with pytest.raises(RuntimeError):
        DeploymentActivator(installation).activate(candidate)
    assert (installation / MANIFEST_NAME).read_bytes() == old
    assert compose_calls[-1][0] == failure
    assert not any(
        call[0] == "up" and APPLICATION_SERVICES[0] in call for call in compose_calls
    )
    if failure == "pull":
        assert not any(call[0] == "stop" for call in compose_calls)


@pytest.mark.parametrize(
    "failure", ["activation_record", "compose", "manifest", CURRENT_RELEASE_NAME]
)
def test_interrupted_promotion_recovers_without_an_unnecessary_restart(
    installation, bundle, compose_calls, monkeypatch, failure
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
        should_fail = should_inject_write_failure(failure, path, content, installation)
        if should_fail and not failed:
            failed = True
            raise OSError("injected")
        real_write(path, content, **kwargs)

    def replace(source, target):
        nonlocal failed
        if (
            failure == CURRENT_RELEASE_NAME
            and target == installation / CURRENT_RELEASE_NAME
            and not failed
        ):
            failed = True
            raise OSError("injected")
        real_replace(source, target)

    monkeypatch.setattr(state_module, "write_private", write)
    monkeypatch.setattr(state_module.os, "replace", replace)
    with pytest.raises(OSError):
        DeploymentActivator(installation).activate(bundle)
    assert DeploymentState(installation).pending()
    DeploymentActivator(installation).activate(bundle)
    assert len(activations) == (2 if failure == "activation_record" else 1)
    assert DeploymentState(installation).pending() is None
    assert (installation / CURRENT_RELEASE_NAME).resolve() == bundle


def test_incompatible_rollback_remains_closed(
    installation, bundle, compose_calls, monkeypatch, tmp_path
):
    DeploymentActivator(installation).activate(bundle)
    candidate = make_bundle(installation / RELEASES_DIRECTORY_NAME / "candidate", "b")
    compose_calls.clear()

    def run(self, *args):
        compose_calls.append(args)
        if args[-1] == DeploymentService.CHECK:
            raise RuntimeError("schema incompatible")

    monkeypatch.setattr(ComposeProject, "run", run)
    with pytest.raises(RuntimeError):
        DeploymentActivator(installation).activate(candidate, rollback=True)
    assert compose_calls[-1] == (
        "run",
        "--rm",
        "--no-deps",
        DeploymentService.MIGRATE,
        DeploymentService.CHECK,
    )
    assert DeploymentState(installation).pending().rollback
    with pytest.raises(ValueError, match="operation differs"):
        DeploymentActivator(installation).activate(candidate)


def test_infrastructure_update_rejected_before_compose_calls(
    installation, bundle, compose_calls, tmp_path
):
    DeploymentActivator(installation).activate(bundle)
    candidate = make_bundle(installation / RELEASES_DIRECTORY_NAME / "candidate", "b")
    values = ReleaseImages.read(candidate / RELEASE_IMAGE_MANIFEST_FILENAME).to_values()
    values[ImageField.POSTGRES] = "postgres@sha256:" + "f" * 64
    write_manifest(candidate / RELEASE_IMAGE_MANIFEST_FILENAME, values)
    refresh_bundle(candidate)
    compose_calls.clear()
    with pytest.raises(ValueError, match="maintenance"):
        DeploymentActivator(installation).activate(candidate)
    assert not compose_calls


def test_lock_and_private_inputs_fail_before_compose_calls(
    installation, bundle, compose_calls
):
    with (installation / LOCK_NAME).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already running"):
            DeploymentActivator(installation).activate(bundle)
    (installation / RUNTIME_CONFIGURATION_NAME).chmod(0o644)
    with pytest.raises(ValueError, match="mode 600"):
        DeploymentActivator(installation).activate(bundle)
    assert not compose_calls


@pytest.mark.parametrize(
    "field,value",
    [
        (JournalField.DIRECTORY, "../escape"),
        (JournalField.PHASE, "unknown"),
        (JournalField.ROLLBACK, "false"),
    ],
)
def test_corrupt_journal_blocks_all_mutation(
    installation, bundle, compose_calls, field, value
):
    DeploymentActivator(installation).activate(bundle)
    state = DeploymentState(installation)
    attempt = state.prepare(
        RuntimeManifest.read(state.manifest),
        state.compose_file.read_bytes(),
        rollback=False,
    )
    record = attempt.to_record()
    record[field] = value
    write_private(state.journal, json.dumps(record).encode())
    compose_calls.clear()
    with pytest.raises(
        ValueError, match="^" + re.escape(INVALID_JOURNAL_MESSAGE) + "$"
    ):
        DeploymentActivator(installation).activate(bundle)
    assert not compose_calls


def test_explicit_forward_repair_replaces_failed_attempt(
    installation, bundle, compose_calls, monkeypatch, tmp_path
):
    activation = BetaRelease.activate

    def fail_activation(*args, **kwargs):
        raise RuntimeError("failure")

    monkeypatch.setattr(BetaRelease, "activate", fail_activation)
    with pytest.raises(RuntimeError):
        DeploymentActivator(installation).activate(bundle)
    repair = make_bundle(installation / RELEASES_DIRECTORY_NAME / "repair", "b")
    monkeypatch.setattr(BetaRelease, "activate", activation)
    DeploymentActivator(installation).activate(repair)
    assert ReleaseImages.read(installation / MANIFEST_NAME).source_commit == "b" * 40


def should_inject_write_failure(failure, path, content, installation):
    return (
        (
            failure == "activation_record"
            and path.name == JOURNAL_NAME
            and json.loads(content)[JournalField.PHASE] == AttemptPhase.ACTIVATED
        )
        or (failure == "compose" and path == installation / HOST_COMPOSE_NAME)
        or (failure == "manifest" and path == installation / MANIFEST_NAME)
    )
