"""Process-boundary preflight and active-pointer failure behavior."""

import io
import json
import os
import subprocess
import sys
import tarfile
from unittest.mock import Mock

import pytest

from control_plane.beta_host_fixture import make_bundle
from control_plane.test_deployment_contracts import inventory_values
from control_plane.test_release_automation import bundle_archive
from scripts.beta_backup.download import RecoveryDownload
from scripts.beta_backup.workflow import BackupWorkflow
from scripts.beta_release.activation import DeploymentActivator
from scripts.beta_release.selection import ActivationSelection
from scripts.deployment.bootstrap_inputs import BootstrapInputs
from scripts.deployment.bundle import ReleaseBundle
from scripts.deployment.bundle.contracts import (
    BUNDLE_METADATA_FILENAME,
    RELEASE_BUNDLE_FILENAME,
    RELEASE_IMAGE_MANIFEST_FILENAME,
)
from scripts.deployment.bundle.installation import InstalledBundle
from scripts.deployment.bundle.source import read_committed_contents
from scripts.deployment.controller import ControllerOperation
from scripts.deployment.dotenv import parse_values, write_manifest
from scripts.deployment.github import GitHubRelease
from scripts.deployment.identity import DeploymentOperation
from scripts.deployment.images import ReleaseImages
from scripts.deployment.inventory import (
    SUPPORTED_ARCHITECTURES,
    SUPPORTED_DISTRIBUTION,
    DeploymentInventory,
)
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import (
    CURRENT_RELEASE_NAME,
    OPERATIONS_CONFIGURATION_NAME,
    RELEASES_DIRECTORY_NAME,
    REPOSITORY,
)
from scripts.deployment.runtime_contracts import DEFAULT_HTTP_PORT
from scripts.deployment.state import DeploymentState
from scripts.deployment.tailscale import (
    PRIVATE_HTTPS_PORT,
    BackendState,
    PrivateServe,
    TailnetStatus,
)
from scripts.host_operations import HostOperations
from scripts.host_operations.probes import certificate_expiry
from scripts.local_docker import LocalDocker
from scripts.private_files import PRIVATE_FILE_MODE, write_private


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_platform_cli_contract(architecture):
    payload = {
        "_meta": {
            "hostvars": {"host": inventory_values() | {"polybot_arch": architecture}}
        }
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.deployment.controller",
            ControllerOperation.PLATFORM,
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == f"platform=linux/{architecture}\n"
    assert not result.stderr


@pytest.mark.parametrize("valid", [True, False])
def test_inputs_cli_private_file_and_sanitized_failure(tmp_path, valid):
    environment = os.environ | {
        "PYTHONPATH": str(REPOSITORY),
        "RELEASE_TAG": "v1.2.3",
        "RELEASE_COMMIT": "a" * 40,
        "REGISTRY_USERNAME": "fixture",
        "REGISTRY_TOKEN": "private-token",
        "OPERATION": DeploymentOperation.DEPLOY
        if valid
        else "private-invalid-operation",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.deployment.controller",
            ControllerOperation.INPUTS,
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    destination = tmp_path / "deploy-inputs.json"
    assert result.returncode == (0 if valid else 1)
    assert not result.stdout
    assert "private-" not in result.stderr
    if valid:
        data = json.loads(destination.read_text())
        assert data["registry_token"] == environment["REGISTRY_TOKEN"]
        assert data["release_bundle"] == str(
            tmp_path / "bundle" / RELEASE_BUNDLE_FILENAME
        )
        assert destination.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    else:
        assert not destination.exists()


@pytest.mark.parametrize("pointer", ["missing", "wrong", "regular"])
def test_activation_repairs_invalid_current_pointer(
    installation, bundle, compose_calls, pointer
):
    activator = DeploymentActivator(installation)
    activator.activate(bundle)
    current = installation / CURRENT_RELEASE_NAME
    current.unlink()
    if pointer == "wrong":
        current.symlink_to(installation / "wrong")
    if pointer == "regular":
        current.write_text("wrong")
    write_private(
        installation / OPERATIONS_CONFIGURATION_NAME,
        json.dumps(
            {
                "origin": "https://host.example.ts.net",
                "alert_to": "operator@example.com",
                "remote": "backup:/backups/polybot",
            }
        ).encode(),
    )
    with pytest.raises(ValueError, match="active release pointer"):
        HostOperations(installation).release()
    compose_calls.clear()
    activator.activate(bundle)
    assert current.is_symlink() and current.resolve() == bundle.resolve()
    assert ("pull",) in compose_calls


@pytest.mark.parametrize("state", list(BackendState))
def test_known_tailnet_enrollment_states(state):
    assert TailnetStatus.from_record({"BackendState": state}).running == (
        state is BackendState.RUNNING
    )


def test_unknown_tailnet_state_rejected_before_enrollment():
    with pytest.raises(ValueError):
        TailnetStatus.from_record({"BackendState": "MysteryState"})


@pytest.mark.parametrize(
    "certificate", [None, [], {}, {"notAfter": 42}, {"notAfter": "invalid"}]
)
def test_malformed_certificate_is_owned_validation_failure(certificate):
    with pytest.raises(ValueError, match="certificate expiry"):
        certificate_expiry(certificate)


@pytest.fixture
def bootstrap_credentials(tmp_path):
    private_key = tmp_path / "key"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
        capture_output=True,
    )
    public_key = private_key.with_suffix(".pub").read_text()
    identity = tmp_path / "age.key"
    subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
    recipient = subprocess.check_output(["age-keygen", "-y", str(identity)], text=True)
    inventory = DeploymentInventory.model_validate(inventory_values())
    return {
        "ssh_public_key": public_key,
        "sftp_private_key": private_key.read_text(),
        "sftp_known_hosts": f"{inventory.sftp_host} {public_key}",
        "age_recipients": recipient,
        "smtp_username": "fixture",
        "smtp_password": "fixture-password",
        "tailscale_authkey": "tskey-auth-fixture",
    }


@pytest.mark.parametrize(
    "field",
    [
        None,
        "ssh_public_key",
        "sftp_private_key",
        "sftp_known_hosts",
        "age_recipients",
        "smtp_username",
        "tailscale_authkey",
    ],
)
def test_bootstrap_real_key_preflight(bootstrap_credentials, field):
    values = bootstrap_credentials | ({field: "invalid"} if field else {})
    if field == "smtp_username":
        values[field] = "   "
    inventory = DeploymentInventory.model_validate(inventory_values())
    if field:
        with pytest.raises((ValueError, subprocess.SubprocessError)):
            BootstrapInputs.model_validate(values).require_valid(inventory)
    else:
        BootstrapInputs.model_validate(values).require_valid(inventory)


@pytest.mark.parametrize(
    "endpoint",
    [
        "unix://",
        "unix://relative",
        "unix:///",
        "unix:///a\nunix:///b",
        "tcp://localhost:2375",
    ],
)
def test_local_docker_rejects_malformed_endpoint(monkeypatch, endpoint):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: endpoint)
    with pytest.raises(ValueError):
        LocalDocker.from_context()


@pytest.mark.parametrize(
    "field", ["polybot_http_port", "polybot_smtp_port", "polybot_sftp_port"]
)
def test_inventory_rejects_boolean_ports(field):
    with pytest.raises(ValueError):
        DeploymentInventory.model_validate(inventory_values() | {field: True})


def test_dotenv_rejects_duplicate_and_malformed_assignments():
    for value in ["NAME=one\nNAME=two", "NAME\nNAME=two", "NAME='unterminated"]:
        with pytest.raises(ValueError):
            parse_values(value)


def test_inventory_cli_exports_normalized_configuration():
    payload = {
        "variables": inventory_values()
        | {
            "polybot_smtp_host": "SMTP.Example.COM.",
            "polybot_sftp_directory": "/backups/polybot/",
        },
        "host_count": 1,
        "host_distribution": SUPPORTED_DISTRIBUTION,
        "host_architecture": SUPPORTED_ARCHITECTURES["amd64"],
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.deployment.controller",
            ControllerOperation.INVENTORY,
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    normalized = json.loads(result.stdout)["variables"]
    assert normalized["polybot_smtp_host"] == "smtp.example.com"
    assert normalized["polybot_sftp_directory"] == "/backups/polybot"


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_recovery_preserves_existing_release_before_download(tmp_path, kind):
    release = tmp_path / "release"
    if kind == "directory":
        release.mkdir()
    else:
        release.symlink_to(tmp_path / "unrelated")
    remote = Mock()
    with pytest.raises(ValueError):
        RecoveryDownload(remote).prepare("archive", tmp_path)
    remote.download.assert_not_called()
    assert release.is_dir() or release.is_symlink()


@pytest.mark.parametrize("failure", ["provenance", "snapshot", "upload"])
def test_backup_workflow_validates_identity_and_prunes_after_attempt(
    tmp_path, monkeypatch, failure
):
    bundle = bundle_archive(tmp_path / RELEASE_BUNDLE_FILENAME)
    release = Mock()
    release.settings.images.source_commit = (
        "b" if failure == "provenance" else "a"
    ) * 40
    remote = Mock()
    snapshot = Mock(return_value=tmp_path / "archive")
    prune = Mock()
    monkeypatch.setattr(
        "scripts.beta_backup.workflow.BetaBackup",
        Mock(return_value=Mock(create=snapshot)),
    )
    monkeypatch.setattr(
        "scripts.beta_backup.workflow.BackupArchives",
        Mock(return_value=Mock(prune_staging=prune)),
    )
    if failure == "snapshot":
        snapshot.side_effect = RuntimeError("snapshot failed")
    if failure == "upload":
        remote.upload.side_effect = RuntimeError("upload failed")
    with pytest.raises((ValueError, RuntimeError)):
        BackupWorkflow(release, remote, tmp_path / "recipients", tmp_path).create(
            bundle
        )
    if failure == "provenance":
        snapshot.assert_not_called()
        remote.upload.assert_not_called()
        prune.assert_not_called()
    else:
        prune.assert_called_once()


@pytest.mark.parametrize("kind", ["root", "member"])
def test_installed_symlinks_fail_before_docker(
    installation, bundle, compose_calls, tmp_path, kind
):
    if kind == "root":
        linked = installation / RELEASES_DIRECTORY_NAME / "link"
        linked.symlink_to(bundle)
        candidate = linked
    else:
        member = bundle / "README.md"
        member.unlink()
        member.symlink_to(tmp_path / "outside")
        candidate = bundle
    with pytest.raises((ValueError, OSError)):
        DeploymentActivator(installation).activate(candidate)
    assert not compose_calls


@pytest.mark.parametrize("kind", ["directory", "symlink", "missing_metadata"])
def test_archive_rejects_nonregular_members_and_absent_metadata(tmp_path, kind):
    bundle = bundle_archive(tmp_path / RELEASE_BUNDLE_FILENAME)
    with tarfile.open(bundle) as source:
        members = [(entry, source.extractfile(entry).read()) for entry in source]
    with tarfile.open(bundle, "w:gz") as target:
        for entry, data in members:
            if kind == "missing_metadata" and entry.name == BUNDLE_METADATA_FILENAME:
                continue
            if kind != "missing_metadata" and entry.name == "README.md":
                entry.type = tarfile.DIRTYPE if kind == "directory" else tarfile.SYMTYPE
                entry.linkname = "/outside"
                entry.size = 0
                target.addfile(entry)
            else:
                target.addfile(entry, io.BytesIO(data))
    with pytest.raises(ValueError):
        ReleaseBundle.from_archive(bundle)


@pytest.mark.parametrize("kind", ["tag", "asset"])
def test_github_rejects_ambiguous_release_records(kind):
    record = {
        "tag_name": "v1.0.0",
        "draft": False,
        "assets": [{"name": RELEASE_BUNDLE_FILENAME}],
    }
    pages = (
        [[record], [record]]
        if kind == "tag"
        else [[record | {"assets": record["assets"] * 2}]]
    )
    with pytest.raises(ValueError):
        GitHubRelease.parse_pages(pages)


@pytest.mark.parametrize("kind", ["path", "compose"])
def test_pending_attempt_rejects_changed_same_commit_bundle(
    installation, bundle, compose_calls, kind
):
    installed = InstalledBundle.read(bundle, installation)
    state = DeploymentState(installation)
    selected = ActivationSelection.read(state, installed, rollback=False)
    attempt = state.prepare(selected.settings, installed.compose_yaml, rollback=False)
    state.begin_activation(attempt)
    if kind == "path":
        alternate = make_bundle(
            installation / RELEASES_DIRECTORY_NAME / "alternate", "a"
        )
        installed = InstalledBundle.read(alternate, installation)
    else:
        attempt.compose_file.write_bytes(b"changed")
    with pytest.raises(ValueError, match="pending attempt differs"):
        ActivationSelection.read(state, installed, rollback=False)
    assert state.journal.exists() and not compose_calls


def test_active_image_mismatch_rejects_operational_source(
    installation, bundle, compose_calls
):
    DeploymentActivator(installation).activate(bundle)
    state = DeploymentState(installation)
    other = make_bundle(installation / RELEASES_DIRECTORY_NAME / "other", "b")
    settings = RuntimeManifest.read(state.manifest).with_images(
        ReleaseImages.read(other / RELEASE_IMAGE_MANIFEST_FILENAME)
    )
    write_manifest(state.manifest, settings.to_values())
    write_private(
        installation / OPERATIONS_CONFIGURATION_NAME,
        json.dumps(
            {
                "origin": "https://host.example.ts.net",
                "alert_to": "operator@example.com",
                "remote": "backup:/backups/polybot",
            }
        ).encode(),
    )
    with pytest.raises(ValueError, match="bundle differs"):
        HostOperations(installation).release()


@pytest.mark.parametrize("kind", ["provenance", "symlink"])
def test_committed_source_rejects_wrong_checkout_and_tracked_symlink(
    tmp_path, monkeypatch, kind
):
    archive = bundle_archive(tmp_path / RELEASE_BUNDLE_FILENAME)
    release = ReleaseBundle.from_archive(archive)
    images = tmp_path / RELEASE_IMAGE_MANIFEST_FILENAME
    write_manifest(images, release.images.to_values())
    (tmp_path / "README.md").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda command, **kwargs: (
            ("b" if kind == "provenance" else "a") * 40
            if "rev-parse" in command
            else b"README.md\0"
        ),
    )
    monkeypatch.setattr(subprocess, "run", Mock())
    with pytest.raises(ValueError):
        read_committed_contents(tmp_path, images)


@pytest.mark.parametrize(
    "state,dns",
    [
        (BackendState.STOPPED, "host.example.ts.net"),
        (BackendState.RUNNING, "other.example.ts.net"),
    ],
)
def test_tailnet_identity_requires_running_matching_dns(state, dns):
    with pytest.raises(ValueError):
        TailnetStatus.from_record(
            {"BackendState": state, "Self": {"DNSName": dns}}
        ).require_origin("https://host.example.ts.net")


@pytest.mark.parametrize("change", ["port", "proxy", "https"])
def test_private_serve_requires_exact_listener_and_proxy(change):
    port = PRIVATE_HTTPS_PORT + 1 if change == "port" else PRIVATE_HTTPS_PORT
    proxy = (
        "http://127.0.0.1:1"
        if change == "proxy"
        else f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"
    )
    record = {
        "TCP": {str(port): {"HTTPS": change != "https"}},
        "Web": {f"host.example.ts.net:{port}": {"Handlers": {"/": {"Proxy": proxy}}}},
    }
    with pytest.raises(ValueError):
        PrivateServe.from_record(record).require_endpoint(
            "https://host.example.ts.net", DEFAULT_HTTP_PORT
        )


def test_bootstrap_rejects_private_key_in_public_key_field(bootstrap_credentials):
    inputs = BootstrapInputs.model_validate(
        bootstrap_credentials
        | {"ssh_public_key": bootstrap_credentials["sftp_private_key"]}
    )
    with pytest.raises(ValueError, match="public-key record"):
        inputs.require_valid(DeploymentInventory.model_validate(inventory_values()))
