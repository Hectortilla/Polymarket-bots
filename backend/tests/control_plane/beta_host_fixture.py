"""Shared installed-host fixtures for deployment boundary tests."""

import hashlib
import json

import pytest
from api.auth.config import AUTH_ORIGIN_ENV
from api.auth.mail.config import SMTP_FROM_ENV, SMTP_HOST_ENV
from api.deployment.release import RELEASE_ID_ENV

from scripts.beta_release import BetaRelease
from scripts.compose_project import ComposeProject
from scripts.deployment.bundle.contracts import (
    BUNDLE_METADATA_FILENAME,
    RELEASE_IMAGE_MANIFEST_FILENAME,
    REQUIRED_FILES,
)
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.images import IMAGE_FIELDS, ImageField, ReleaseImages
from scripts.deployment.paths import (
    COMPOSE_FILE,
    RELEASES_DIRECTORY_NAME,
    RUNTIME_CONFIGURATION_NAME,
    SECRETS_DIRECTORY_NAME,
    SOURCE_COMPOSE_PATH,
)
from scripts.deployment.runtime_contracts import (
    DEFAULT_HTTP_PORT,
    HTTP_PORT_ENV,
    SECRETS_DIRECTORY_ENV,
)
from scripts.deployment.storage import SecretFile
from scripts.private_files import write_private


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "host"
    root.mkdir(mode=0o700)
    secrets = root / SECRETS_DIRECTORY_NAME
    secrets.mkdir(mode=0o700)
    for name in SecretFile:
        write_private(secrets / name, b"fixture", mode=0o444)
    write_manifest(
        root / RUNTIME_CONFIGURATION_NAME,
        {
            AUTH_ORIGIN_ENV: "https://host.example.ts.net",
            HTTP_PORT_ENV: str(DEFAULT_HTTP_PORT),
            SECRETS_DIRECTORY_ENV: str(secrets),
            SMTP_HOST_ENV: "smtp.example.com",
            SMTP_FROM_ENV: "accounts@example.com",
        },
    )
    return root


@pytest.fixture
def bundle(installation):
    return make_bundle(installation / RELEASES_DIRECTORY_NAME / "v1.0.0", "a")


def make_bundle(path, marker):
    path.mkdir(parents=True)
    values = {
        field: f"ghcr.io/test/image-{index}@sha256:" + str(index) * 64
        for index, field in enumerate(IMAGE_FIELDS, 1)
    }
    values[ImageField.BACKEND] = "ghcr.io/test/backend@sha256:" + marker * 64
    values[RELEASE_ID_ENV] = marker * 40
    for name in REQUIRED_FILES - {RELEASE_IMAGE_MANIFEST_FILENAME}:
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            COMPOSE_FILE.read_bytes()
            if name == str(SOURCE_COMPOSE_PATH)
            else b"fixture"
        )
    write_manifest(path / RELEASE_IMAGE_MANIFEST_FILENAME, values)
    refresh_bundle(path)
    return path


def refresh_bundle(path):
    images = ReleaseImages.read(path / RELEASE_IMAGE_MANIFEST_FILENAME)
    (path / BUNDLE_METADATA_FILENAME).write_text(
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
def compose_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ComposeProject, "require_local_docker", lambda self: calls.append(("local",))
    )
    monkeypatch.setattr(ComposeProject, "run", lambda self, *args: calls.append(args))
    monkeypatch.setattr(
        BetaRelease, "require_healthy", lambda self: calls.append(("healthy",))
    )
    return calls
