"""Publication provenance, reusable gates and secret-free release assets."""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.deployment import publication
from scripts.deployment.bundle import (
    BUNDLE_NAME,
    METADATA_NAME,
    REQUIRED_FILES,
    validate_tag,
    verify,
)
from scripts.deployment.images import IMAGE_FIELDS


def bundle_archive(path, *, commit="a" * 40, tag="v1.2.3", mutation=None):
    contents = {name: b"fixture" for name in REQUIRED_FILES}
    contents["images.env"] = (
        "POLYBOT_RELEASE_ID="
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
    contents[METADATA_NAME] = json.dumps(metadata).encode()
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
    assert validate_tag(tag) == tag


@pytest.mark.parametrize("tag", ["v1.2", "v01.2.3", "v1.2.3-rc", "../tag", "v1.2.3\n"])
def test_invalid_version_tags(tag):
    with pytest.raises(ValueError):
        validate_tag(tag)


def test_bundle_rejects_moved_tag_content_corruption_and_path_traversal(tmp_path):
    path = bundle_archive(tmp_path / BUNDLE_NAME)
    assert verify(path, commit="a" * 40, tag="v1.2.3")["commit"] == "a" * 40
    with pytest.raises(ValueError, match="provenance"):
        verify(path, commit="b" * 40)
    bundle_archive(
        path, mutation=lambda data: data.update({"deploy/compose.yaml": b"corrupt"})
    )
    with pytest.raises(ValueError, match="checksum"):
        verify(path)
    bundle_archive(path, mutation=lambda data: data.update({"../escape": b"bad"}))
    with pytest.raises(ValueError, match="unsafe"):
        verify(path)


def test_release_reuse_verifies_downloaded_provenance(tmp_path, monkeypatch):
    release = {"tag_name": "v1.2.3", "draft": False, "assets": [{"name": BUNDLE_NAME}]}
    monkeypatch.setattr(
        publication.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps([[release]]),
    )

    def download(*args, **kwargs):
        bundle_archive(tmp_path / BUNDLE_NAME)

    monkeypatch.setattr(publication.subprocess, "run", download)
    assert publication.published("v1.2.3", "a" * 40, tmp_path)
    with pytest.raises(ValueError, match="provenance"):
        publication.published("v1.2.3", "b" * 40, tmp_path)


@pytest.mark.parametrize(
    "draft,assets",
    [
        (True, []),
        (True, [{"name": BUNDLE_NAME}]),
        (False, []),
        (False, [{"name": "unexpected"}]),
    ],
)
def test_partial_publication_is_never_overwritten(tmp_path, monkeypatch, draft, assets):
    monkeypatch.setattr(
        publication.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(
            [[{"tag_name": "v1.2.3", "draft": draft, "assets": assets}]]
        ),
    )
    download = Mock()
    monkeypatch.setattr(publication.subprocess, "run", download)
    with pytest.raises(ValueError, match="partial/conflicting"):
        publication.published("v1.2.3", "a" * 40, tmp_path)
    download.assert_not_called()


def test_registry_or_github_failure_does_not_mean_absent_release(tmp_path, monkeypatch):
    monkeypatch.setattr(
        publication.subprocess,
        "check_output",
        Mock(side_effect=subprocess.CalledProcessError(1, "gh")),
    )
    with pytest.raises(subprocess.CalledProcessError):
        publication.published("v1.2.3", "a" * 40, tmp_path)


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
    from scripts.deployment.bundle import create
    from scripts.deployment.dotenv import write_manifest

    source = tmp_path / "source"
    source.mkdir()
    for name in REQUIRED_FILES - {"images.env"}:
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
    images = tmp_path / "images.env"
    write_manifest(
        images,
        {
            "POLYBOT_RELEASE_ID": commit,
            **{
                field: "ghcr.io/test/image@sha256:" + "a" * 64 for field in IMAGE_FIELDS
            },
        },
    )
    output = tmp_path / BUNDLE_NAME
    create(source, images, "v1.0.0", output)
    assert ".env" not in verify(output)["files"]
    (source / "deploy/compose.yaml").write_text("dirty")
    with pytest.raises(subprocess.CalledProcessError):
        create(source, images, "v1.0.1", tmp_path / "dirty.tar.gz")
