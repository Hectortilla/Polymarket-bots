"""Production startup and non-destructive release ordering contracts."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from api.auth.config import AUTH_ALLOW_HTTP_ENV, AUTH_ORIGIN_ENV
from api.database import DATABASE_URL_ENV
from api.deployment.__main__ import main as deployment_main
from api.deployment.secrets import configured_secret
from api.deployment.settings import (
    DEFAULT_HEARTBEAT_SECONDS,
    ENVIRONMENT_ENV,
    PROXY_ADDRESS_ENV,
    RELEASE_ID_ENV,
    Environment,
    StartupSettings,
)
from api.execution.config import REDIS_URL_ENV
from scripts.beta_release import APPLICATION_SERVICES, IMAGE_VARIABLES, BetaRelease


def production_environment(monkeypatch, tmp_path):
    for name, value in (
        (DATABASE_URL_ENV, "postgresql://user:secret@postgres/polybot"),
        (REDIS_URL_ENV, "redis://redis:6379/0"),
    ):
        path = tmp_path / name
        path.write_text(value)
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(f"{name}_FILE", str(path))
    monkeypatch.setenv(ENVIRONMENT_ENV, Environment.PRODUCTION)
    monkeypatch.setenv(RELEASE_ID_ENV, "a" * 40)
    monkeypatch.setenv(PROXY_ADDRESS_ENV, "172.30.16.2")
    monkeypatch.setenv(AUTH_ORIGIN_ENV, "https://localhost:8443")
    monkeypatch.setenv(AUTH_ALLOW_HTTP_ENV, "false")


@pytest.mark.parametrize(
    "changes",
    [
        {"worker_concurrency": 0},
        {"heartbeat_seconds": 0},
        {"lease_seconds": 0},
        {"lease_seconds": DEFAULT_HEARTBEAT_SECONDS},
        {"heartbeat_seconds": float("inf")},
        {"proxy_address": "*"},
        {"environment": Environment.PRODUCTION},
    ],
)
def test_startup_rejects_unsafe_numeric_and_proxy_settings(changes):
    with pytest.raises(ValidationError):
        StartupSettings(database_url="hidden", redis_url="hidden", **changes)


def test_production_requires_https_secret_files_and_immutable_release(
    monkeypatch, tmp_path
):
    production_environment(monkeypatch, tmp_path)
    settings = StartupSettings.from_env()
    assert "secret@" not in repr(settings)
    monkeypatch.setenv(AUTH_ALLOW_HTTP_ENV, "true")
    with pytest.raises(ValueError, match="HTTPS"):
        StartupSettings.from_env()
    monkeypatch.setenv(AUTH_ALLOW_HTTP_ENV, "false")
    monkeypatch.setenv(RELEASE_ID_ENV, "latest")
    with pytest.raises(ValueError, match="immutable"):
        StartupSettings.from_env()


def test_secret_ingress_never_silently_falls_back(monkeypatch, tmp_path):
    name = DATABASE_URL_ENV
    path = tmp_path / "secret"
    monkeypatch.setenv(f"{name}_FILE", str(path))
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="cannot read"):
        configured_secret(name, "fallback")
    path.write_text("")
    with pytest.raises(ValueError, match="nonempty"):
        configured_secret(name)
    path.write_text("credential")
    monkeypatch.setenv(name, "other")
    with pytest.raises(ValueError, match="only one"):
        configured_secret(name)


def test_startup_reports_the_invalid_setting_without_credentials(monkeypatch, tmp_path):
    production_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(RELEASE_ID_ENV, "latest")
    monkeypatch.setattr("sys.argv", ["api.deployment", "check"])
    with pytest.raises(SystemExit) as failure:
        deployment_main()
    message = str(failure.value)
    assert "configuration invalid" in message and "immutable release" in message
    assert "secret@" not in message


def release_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "release.env"
    values = {name: "sha256:" + "a" * 64 for name in IMAGE_VARIABLES}
    values.update(
        {
            RELEASE_ID_ENV: "a" * 40,
            AUTH_ORIGIN_ENV: "https://localhost:8443",
            "POLYBOT_SECRETS_DIR": str(tmp_path),
        }
    )
    manifest.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    return manifest


def test_failed_migration_never_activates_release_and_rollback_only_checks_schema(
    tmp_path,
):
    release = BetaRelease(release_manifest(tmp_path), "polybot-test")
    release.compose = Mock(
        side_effect=[None, None, None, None, RuntimeError("migration failed")]
    )
    with pytest.raises(RuntimeError):
        release.activate(rollback=False)
    assert release.compose.call_args_list[2].args == ("stop", APPLICATION_SERVICES[0])
    assert release.compose.call_args_list[3].args == ("stop", *APPLICATION_SERVICES[1:])
    assert release.compose.call_args_list[-1].args[-1] == "migrate"
    assert release.compose.call_count == 5
    release.compose = Mock()
    release.activate(rollback=True)
    assert release.compose.call_args_list[4].args == (
        "run",
        "--rm",
        "--no-deps",
        "migrate",
        "check",
    )
    assert not any("downgrade" in call.args for call in release.compose.call_args_list)


def test_mutable_images_cannot_enter_release(tmp_path):
    path = release_manifest(tmp_path)
    path.write_text(path.read_text().replace("sha256:" + "a" * 64, "latest", 1))
    with pytest.raises(ValueError, match="digest"):
        BetaRelease(path, "polybot-test")
