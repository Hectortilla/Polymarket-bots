"""Regression checks at the changed artifact, config and promotion boundaries."""

import hashlib
import io
import json
import tarfile
from dataclasses import replace
from unittest.mock import Mock

import pytest
from api.deployment.release import RELEASE_ID_ENV

from control_plane.beta_host_fixture import make_bundle
from control_plane.test_release_automation import bundle_archive
from scripts.beta_release import BetaRelease
from scripts.beta_release.activation import DeploymentActivator
from scripts.beta_release.health import (
    HEALTHCHECK_SERVICES,
    REQUIRED_SERVICES,
    parse_compose_status,
)
from scripts.deployment import state as state_module
from scripts.deployment.bundle import ReleaseBundle
from scripts.deployment.bundle.contracts import (
    BUNDLE_METADATA_FILENAME,
    RELEASE_BUNDLE_FILENAME,
    RELEASE_IMAGE_MANIFEST_FILENAME,
)
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.github import GitHubRelease
from scripts.deployment.images import ImagePolicy, ReleaseImages
from scripts.deployment.manifest import RuntimeManifest
from scripts.deployment.paths import CURRENT_RELEASE_NAME, RELEASES_DIRECTORY_NAME
from scripts.deployment.publication import reuse_published_bundle
from scripts.deployment.runtime_contracts import (
    HTTP_PORT_ENV,
    HTTP_PORT_MAXIMUM,
    HTTP_PORT_MINIMUM,
)
from scripts.deployment.state import DeploymentState
from scripts.deployment.tailscale import (
    PrivateServe,
    TailnetStatus,
    validate_private_origin,
)


@pytest.mark.parametrize("ndjson", [False, True])
def test_compose_adapter_requires_probes_but_allows_services_without_healthchecks(
    ndjson, monkeypatch
):
    records = [
        {
            "Service": service,
            "State": "running",
            **({"Health": "healthy"} if service in HEALTHCHECK_SERVICES else {}),
        }
        for service in REQUIRED_SERVICES
    ]
    encode = lambda rows: (
        "\n".join(json.dumps(row) for row in rows) if ndjson else json.dumps(rows)
    )
    monkeypatch.setattr(
        "scripts.beta_release.health.subprocess.check_output",
        lambda *args, **kwargs: encode(records),
    )
    compose = Mock()
    BetaRelease(Mock(), compose).require_healthy()
    records[0].pop("Health")
    with pytest.raises(RuntimeError):
        BetaRelease(Mock(), compose).require_healthy()
    records[0]["Health"] = "unhealthy"
    with pytest.raises(RuntimeError):
        BetaRelease(Mock(), compose).require_healthy()


@pytest.mark.parametrize(
    "rows",
    [
        "bad-json",
        "{}",
        "null",
        "[1]",
        '[{"Service":"api"}]',
        '[{"Service":"api","State":7}]',
        '[{"Service":"api","State":"running","Health":true}]',
        '[{"Service":"api","State":"running"},{"Service":"api","State":"running"}]',
    ],
)
def test_compose_adapter_rejects_malformed_or_duplicate_rows(rows):
    with pytest.raises(ValueError):
        parse_compose_status(rows)


@pytest.mark.parametrize(
    "record",
    [
        [],
        {"Web": []},
        {"AllowFunnel": []},
        {"AllowFunnel": {"host:443": True}},
        {"AllowFunnel": {"host:443": "false"}},
        {"Web": {"host:443": []}},
        {"Web": {"host:443": {"Handlers": []}}},
        {"Foreground": {"1": {"AllowFunnel": {"host:443": True}}}},
    ],
)
def test_serve_adapter_rejects_malformed_or_public_configuration(record):
    with pytest.raises(ValueError):
        PrivateServe.from_record(record)


@pytest.mark.parametrize(
    "origin",
    [
        "http://host.example.ts.net",
        "https://host.example.ts.net/path",
        "https://host.example.ts.net:444",
        "https://example.com",
        "https://-host.example.ts.net",
        "https://host..ts.net",
    ],
)
def test_private_origin_is_exact(origin):
    with pytest.raises(ValueError):
        validate_private_origin(origin)


@pytest.mark.parametrize(
    "record", [[], {}, {"BackendState": True}, {"BackendState": "Running", "Self": []}]
)
def test_tailnet_status_shape_is_validated(record):
    with pytest.raises(ValueError):
        TailnetStatus.from_record(record)


@pytest.mark.parametrize("port", [HTTP_PORT_MINIMUM, HTTP_PORT_MAXIMUM])
def test_manifest_port_roundtrip_is_typed(installation, bundle, compose_calls, port):
    DeploymentActivator(installation).activate(bundle)
    settings = RuntimeManifest.read(DeploymentState(installation).manifest)
    values = settings.to_values() | {HTTP_PORT_ENV: str(port)}
    candidate = RuntimeManifest.from_values(values, policy=ImagePolicy.REGISTRY)
    assert candidate.http_port == port
    assert HTTP_PORT_ENV not in candidate.extra_values
    assert candidate.to_values()[HTTP_PORT_ENV] == str(port)


@pytest.mark.parametrize(
    "mutation",
    ["missing_bundle", "outside", "tampered", "manifest", "compose", "images"],
)
def test_invalid_promotion_never_writes_any_active_pointer(
    installation, bundle, compose_calls, monkeypatch, tmp_path, mutation
):
    DeploymentActivator(installation).activate(bundle)
    state = DeploymentState(installation)
    settings = RuntimeManifest.read(state.manifest)
    if mutation == "images":
        other = make_bundle(installation / RELEASES_DIRECTORY_NAME / "other", "b")
        settings = settings.with_images(
            ReleaseImages.read(other / RELEASE_IMAGE_MANIFEST_FILENAME)
        )
    if mutation == "missing_bundle":
        settings = replace(settings, bundle_directory=None)
    if mutation == "outside":
        settings = replace(
            settings, bundle_directory=make_bundle(tmp_path / "outside", "b")
        )
    attempt = state.prepare(settings, state.compose_file.read_bytes(), rollback=False)
    state.begin_activation(attempt)
    attempt = state.mark_activated(attempt)
    if mutation == "tampered":
        (bundle / "README.md").write_text("changed")
    if mutation == "manifest":
        write_manifest(attempt.manifest, {"invalid": "candidate"})
    if mutation == "compose":
        attempt.compose_file.write_bytes(b"other")
    write = Mock()
    monkeypatch.setattr(state_module, "write_private", write)
    with pytest.raises(ValueError):
        state.promote(attempt)
    write.assert_not_called()
    assert state.journal.exists()
    assert (installation / CURRENT_RELEASE_NAME).resolve() == bundle


def test_fresh_rollback_and_outside_bundle_fail_before_docker(
    installation, bundle, compose_calls, tmp_path
):
    with pytest.raises(ValueError, match="fresh installation"):
        DeploymentActivator(installation).activate(bundle, rollback=True)
    with pytest.raises(ValueError, match="release directory"):
        DeploymentActivator(installation).activate(
            make_bundle(tmp_path / "outside", "b")
        )
    assert not compose_calls


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "metadata_type",
        "commit_type",
        "digest_type",
        "image_provenance",
        "dotenv_missing",
    ],
)
def test_release_archive_metadata_and_members_share_strict_validation(
    tmp_path, mutation
):
    def mutate(contents):
        metadata = json.loads(contents[BUNDLE_METADATA_FILENAME])
        if mutation == "extra":
            contents["extra"] = b"unlisted"
        elif mutation == "missing":
            contents.pop("README.md")
        elif mutation == "metadata_type":
            metadata = []
        elif mutation == "commit_type":
            metadata["commit"] = None
        elif mutation == "digest_type":
            metadata["files"]["README.md"] = True
        elif mutation == "image_provenance":
            metadata["commit"] = "b" * 40
        elif mutation == "dotenv_missing":
            contents[RELEASE_IMAGE_MANIFEST_FILENAME] = (RELEASE_ID_ENV + "\n").encode()
            metadata["files"][RELEASE_IMAGE_MANIFEST_FILENAME] = hashlib.sha256(
                contents[RELEASE_IMAGE_MANIFEST_FILENAME]
            ).hexdigest()
        contents[BUNDLE_METADATA_FILENAME] = json.dumps(metadata).encode()

    path = bundle_archive(tmp_path / RELEASE_BUNDLE_FILENAME, mutation=mutate)
    with pytest.raises(ValueError):
        ReleaseBundle.from_archive(path)


def test_release_archive_rejects_duplicate_regular_members(tmp_path):
    path = bundle_archive(tmp_path / RELEASE_BUNDLE_FILENAME)
    with tarfile.open(path) as source:
        contents = [
            (member.name, source.extractfile(member).read()) for member in source
        ]
    with tarfile.open(path, "w:gz") as archive:
        for name, value in [*contents, contents[0]]:
            member = tarfile.TarInfo(name)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    with pytest.raises(ValueError, match="duplicate"):
        ReleaseBundle.from_archive(path)


@pytest.mark.parametrize(
    "record",
    [
        [],
        [[{"tag_name": "v1.0.0", "draft": "false", "assets": []}]],
        [[{"tag_name": "v1.0.0", "draft": False, "assets": [1]}]],
    ],
)
def test_github_release_adapter_validates_shapes(record):
    if record == []:
        assert GitHubRelease.parse_pages(record) == ()
    else:
        with pytest.raises(ValueError):
            GitHubRelease.parse_pages(record)


def test_no_publication_returns_false_without_download(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.deployment.github.subprocess.check_output",
        lambda *args, **kwargs: "[]",
    )
    download = Mock()
    monkeypatch.setattr(GitHubRelease, "download_bundle", download)
    assert not reuse_published_bundle("v1.0.0", "a" * 40, tmp_path)
    download.assert_not_called()
