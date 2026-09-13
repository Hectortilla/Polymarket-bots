"""Publication provenance, reusable gates and secret-free release assets."""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from api.deployment.release import RELEASE_ID_ENV

from scripts.deployment import github, publication
from scripts.deployment.bundle import ReleaseBundle
from scripts.deployment.bundle.contracts import (
    BUNDLE_METADATA_FILENAME,
    RELEASE_BUNDLE_FILENAME,
    RELEASE_IMAGE_MANIFEST_FILENAME,
    REQUIRED_FILES,
)
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.identity import validate_release_tag
from scripts.deployment.images import IMAGE_FIELDS
from scripts.deployment.paths import SOURCE_COMPOSE_PATH


def bundle_archive(path, *, commit="a" * 40, tag="v1.2.3", mutation=None):
    contents = {name: b"fixture" for name in REQUIRED_FILES}
    contents[RELEASE_IMAGE_MANIFEST_FILENAME] = (
        RELEASE_ID_ENV
        + "="
        + commit
        + "\n"
        + "\n".join(
            field + "=ghcr.io/test/image@sha256:" + "a" * 64 for field in IMAGE_FIELDS
        )
    ).encode()
    metadata = {
        "commit": commit,
        "tag": tag,
        "files": {
            name: hashlib.sha256(value).hexdigest() for name, value in contents.items()
        },
    }
    contents[BUNDLE_METADATA_FILENAME] = json.dumps(metadata).encode()
    if mutation:
        mutation(contents)
    with tarfile.open(path, "w:gz") as archive:
        for name, value in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    return path


@pytest.mark.parametrize("tag", ["v1.2.3", "v0.0.0", "v100.2.3"])
def test_exact_version_tags(tag):
    assert validate_release_tag(tag) == tag


@pytest.mark.parametrize("tag", ["v1.2", "v01.2.3", "v1.2.3-rc", "../tag", "v1.2.3\n"])
def test_invalid_version_tags(tag):
    with pytest.raises(ValueError):
        validate_release_tag(tag)


def test_bundle_rejects_moved_tag_content_corruption_and_path_traversal(tmp_path):
    path = bundle_archive(tmp_path / RELEASE_BUNDLE_FILENAME)
    assert (
        ReleaseBundle.from_archive(path, commit="a" * 40, tag="v1.2.3").metadata.commit
        == "a" * 40
    )
    with pytest.raises(ValueError, match="provenance"):
        ReleaseBundle.from_archive(path, commit="b" * 40)
    bundle_archive(
        path, mutation=lambda data: data.update({str(SOURCE_COMPOSE_PATH): b"corrupt"})
    )
    with pytest.raises(ValueError, match="checksum"):
        ReleaseBundle.from_archive(path)
    bundle_archive(path, mutation=lambda data: data.update({"../escape": b"bad"}))
    with pytest.raises(ValueError, match="unsafe"):
        ReleaseBundle.from_archive(path)


def test_release_reuse_verifies_downloaded_provenance(tmp_path, monkeypatch):
    release = {
        "tag_name": "v1.2.3",
        "draft": False,
        "assets": [{"name": RELEASE_BUNDLE_FILENAME}],
    }
    monkeypatch.setattr(
        github.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps([[release]]),
    )

    def download(*args, **kwargs):
        bundle_archive(tmp_path / RELEASE_BUNDLE_FILENAME)

    monkeypatch.setattr(github.subprocess, "run", download)
    assert publication.reuse_published_bundle("v1.2.3", "a" * 40, tmp_path)
    with pytest.raises(ValueError, match="provenance"):
        publication.reuse_published_bundle("v1.2.3", "b" * 40, tmp_path)


@pytest.mark.parametrize(
    "draft,assets",
    [
        (True, []),
        (True, [{"name": RELEASE_BUNDLE_FILENAME}]),
        (False, []),
        (False, [{"name": "unexpected"}]),
    ],
)
def test_partial_publication_is_never_overwritten(tmp_path, monkeypatch, draft, assets):
    monkeypatch.setattr(
        github.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(
            [[{"tag_name": "v1.2.3", "draft": draft, "assets": assets}]]
        ),
    )
    download = Mock()
    monkeypatch.setattr(github.subprocess, "run", download)
    with pytest.raises(ValueError, match="partial/conflicting"):
        publication.reuse_published_bundle("v1.2.3", "a" * 40, tmp_path)
    download.assert_not_called()


def test_registry_or_github_failure_does_not_mean_absent_release(tmp_path, monkeypatch):
    monkeypatch.setattr(
        github.subprocess,
        "check_output",
        Mock(side_effect=subprocess.CalledProcessError(1, "gh")),
    )
    with pytest.raises(subprocess.CalledProcessError):
        publication.reuse_published_bundle("v1.2.3", "a" * 40, tmp_path)


def test_workflows_share_validation_and_connect_only_after_builds():
    release = Path(".github/workflows/release.yml").read_text()
    assert "cancel-in-progress: false" in release
    assert "needs: bundle" in release and "needs: validate" in release
    assert "uses: ./.github/workflows/ci.yml" in release
    assert "operation:" in release and "options: [deploy, rollback]" in release
    assert "git merge-base --is-ancestor" in release
    assert (
        "steps.backend.outputs.digest" in release
        and "steps.frontend.outputs.digest" in release
    )
    assert "--clobber" not in release
    assert "audience:" in release and "id-token: write" in release
    assert release.index("tailscale/github-action") > release.index(
        "docker/build-push-action"
    )
    for filename in ["accounts", "frontend", "deployment"]:
        assert "workflow_call:" in Path(f".github/workflows/{filename}.yml").read_text()


def test_create_bundles_only_committed_operational_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in REQUIRED_FILES - {RELEASE_IMAGE_MANIFEST_FILENAME}:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    (source / ".gitignore").write_text(".env\n")
    (source / ".env").write_text("must never ship")
    for arguments in [
        ["init"],
        ["config", "user.name", "Fixture"],
        ["config", "user.email", "fixture@example.com"],
        ["add", "."],
        ["commit", "-m", "fixture"],
    ]:
        subprocess.run(["git", *arguments], cwd=source, check=True, capture_output=True)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    images = tmp_path / RELEASE_IMAGE_MANIFEST_FILENAME
    write_manifest(
        images,
        {
            RELEASE_ID_ENV: commit,
            **{
                field: "ghcr.io/test/image@sha256:" + "a" * 64 for field in IMAGE_FIELDS
            },
        },
    )
    output = tmp_path / RELEASE_BUNDLE_FILENAME
    ReleaseBundle.create(source, images, "v1.0.0", output)
    assert ".env" not in ReleaseBundle.from_archive(output).metadata.files
    (source / str(SOURCE_COMPOSE_PATH)).write_text("dirty")
    with pytest.raises(subprocess.CalledProcessError):
        ReleaseBundle.create(source, images, "v1.0.1", tmp_path / "dirty.tar.gz")
