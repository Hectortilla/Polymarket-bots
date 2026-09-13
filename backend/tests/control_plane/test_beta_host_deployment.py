"""Laptop publishing and host deployment safety without registry or daemon mutations."""

import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from api.auth.config import AuthSettings
from api.auth.mail.config import (
    SMTP_FROM_ENV,
    SMTP_PORT_ENV,
    SMTP_SECURITY_ENV,
    SmtpSecurity,
    SmtpSettings,
)
from api.deployment.release import RELEASE_ID_ENV
from api.deployment.services import (
    APPLICATION_SERVICES,
    ENTRYPOINT_SERVICE,
    POSTGRES_SERVICE,
    REDIS_SERVICE,
    DeploymentService,
)
from dotenv import dotenv_values
from polybot.framework.config.constants import BOT_MODE_ENV
from polybot.framework.config.mode import BotMode
from pydantic import SecretStr

from scripts import beta_publish, beta_setup, beta_start, ghcr
from scripts.beta_publish import DEFAULT_POSTGRES_IMAGE, DEFAULT_REDIS_IMAGE
from scripts.beta_release import BetaRelease
from scripts.beta_start import LOG_TAIL_LINES, start
from scripts.compose_project import DOCKER_HOST_ENV, ComposeProject
from scripts.deployment import source, storage
from scripts.deployment import state as state_module
from scripts.deployment.attempt import (
    HISTORY_DIRECTORY_NAME,
    INVALID_JOURNAL_MESSAGE,
    JOURNAL_NAME,
    LOCK_NAME,
    PREVIOUS_MANIFEST_NAME,
    AttemptPhase,
    JournalField,
)
from scripts.deployment.buildx import (
    BuildPlatform,
    reference_from_metadata,
)
from scripts.deployment.dotenv import write_manifest
from scripts.deployment.images import (
    IMAGE_FIELDS,
    ImageField,
    ImagePolicy,
    ImageReference,
    ReleaseImages,
)
from scripts.deployment.manifest import (
    DEFAULT_AUTH_ORIGIN,
    DEFAULT_HTTPS_PORT,
    DEFAULT_SMTP_PORT,
    HTTPS_PORT_ENV,
    RuntimeManifest,
)
from scripts.deployment.paths import (
    COMPOSE_FILE,
    HOST_COMPOSE_NAME,
    MANIFEST_NAME,
    SECRETS_DIRECTORY_NAME,
    SOURCE_COMPOSE_PATH,
)
from scripts.deployment.source import SourceSnapshot
from scripts.deployment.state import DeploymentState
from scripts.deployment.storage import CONTAINER_SECRET_MODE, SecretFile
from scripts.private_files import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    read_regular,
    write_private,
)


@pytest.fixture
def image_manifest(tmp_path):
    manifest = tmp_path / "images.env"
    images = {
        name: f"ghcr.io/test/image-{index}@sha256:{index:x}" + f"{index:x}" * 63
        for index, name in enumerate(IMAGE_FIELDS, start=1)
    }
    images[RELEASE_ID_ENV] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    write_manifest(manifest, images)
    return manifest


@pytest.fixture(scope="module")
def certificate(tmp_path_factory):
    directory = tmp_path_factory.mktemp("tls")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


@pytest.fixture
def configured_app(tmp_path, image_manifest, certificate):
    app = tmp_path / "app"
    smtp = SmtpSettings(
        host="smtp.example.com",
        port=DEFAULT_SMTP_PORT,
        sender="accounts@example.com",
        username=SecretStr("test-user"),
        password=SecretStr("$ecret'\\value"),
    )
    beta_setup.setup(app, image_manifest, DEFAULT_AUTH_ORIGIN, smtp, *certificate)
    return app


def test_setup_permissions_credentials_and_committed_compose(configured_app):
    app = configured_app
    assert stat.S_IMODE(app.stat().st_mode) == PRIVATE_DIRECTORY_MODE
    assert stat.S_IMODE((app / MANIFEST_NAME).stat().st_mode) == PRIVATE_FILE_MODE
    secret_dir = app / SECRETS_DIRECTORY_NAME
    assert stat.S_IMODE(secret_dir.stat().st_mode) == PRIVATE_DIRECTORY_MODE
    for secret in secret_dir.iterdir():
        assert stat.S_IMODE(secret.stat().st_mode) == CONTAINER_SECRET_MODE
    password = (secret_dir / SecretFile.POSTGRES_PASSWORD).read_text()
    assert len(password) == 64
    assert password in (secret_dir / SecretFile.DATABASE_URL).read_text()
    assert password not in (app / MANIFEST_NAME).read_text()
    assert (secret_dir / SecretFile.SMTP_PASSWORD).read_text() == "$ecret'\\value"
    assert (app / HOST_COMPOSE_NAME).read_bytes() == COMPOSE_FILE.read_bytes()


def test_setup_rerun_preserves_secrets(configured_app, image_manifest, certificate):
    app = configured_app
    original = (
        app / SECRETS_DIRECTORY_NAME / SecretFile.POSTGRES_PASSWORD
    ).read_bytes()
    with pytest.raises(ValueError, match="not empty"):
        beta_setup.setup(app, image_manifest, DEFAULT_AUTH_ORIGIN, Mock(), *certificate)
    assert (
        app / SECRETS_DIRECTORY_NAME / SecretFile.POSTGRES_PASSWORD
    ).read_bytes() == original


def test_bad_tls_leaves_no_partial_installation(tmp_path, image_manifest):
    invalid = tmp_path / "invalid.pem"
    invalid.write_text("invalid")
    app = tmp_path / "app"
    with pytest.raises(OSError):
        beta_setup.setup(
            app, image_manifest, DEFAULT_AUTH_ORIGIN, Mock(), invalid, invalid
        )
    assert not app.exists()


def test_manifest_round_trips_literal_dotenv_characters(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSWORD", "should-not-expand")
    path = tmp_path / MANIFEST_NAME
    values = {"SETTING": "a'b\\c ${PASSWORD} # end"}
    write_manifest(path, values)
    assert dotenv_values(path, interpolate=False) == values


def test_host_images_reject_local_only_ids(image_manifest):
    values = ReleaseImages.read(image_manifest).to_values()
    values[ImageField.BACKEND] = "sha256:" + "a" * 64
    write_manifest(image_manifest, values)
    with pytest.raises(ValueError, match="pullable"):
        ReleaseImages.read(image_manifest).to_values()


def test_login_passes_token_only_on_stdin(monkeypatch):
    token = "test-registry-token"
    monkeypatch.setenv(ghcr.TOKEN_ENV, token)
    run = Mock()
    monkeypatch.setattr(ghcr.subprocess, "run", run)
    ghcr.login("test-user")
    assert token not in " ".join(run.call_args.args[0])
    assert run.call_args.kwargs["input"] == token + "\n"
    assert ghcr.TOKEN_ENV not in os.environ


@pytest.fixture
def docker_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ComposeProject,
        "require_local_docker",
        lambda self: calls.append(("local-docker",)),
    )
    monkeypatch.setattr(ComposeProject, "run", lambda self, *args: calls.append(args))
    monkeypatch.setattr(ghcr, "login", lambda username: calls.append(("login",)))
    return calls


def test_start_pulls_before_stopping_and_keeps_migration_order(
    configured_app, docker_calls
):
    start(configured_app, "test-user", follow_logs=False)
    pull = docker_calls.index(("pull",))
    stop = docker_calls.index(("stop", APPLICATION_SERVICES[0]))
    migration = docker_calls.index(
        (
            "run",
            "--rm",
            "--no-deps",
            DeploymentService.MIGRATE,
            DeploymentService.MIGRATE,
        )
    )
    assert docker_calls.index(("login",)) < pull < stop < migration
    assert docker_calls[-1][-1] == APPLICATION_SERVICES[0]
    assert list(
        (configured_app / HISTORY_DIRECTORY_NAME).glob(f"*/{PREVIOUS_MANIFEST_NAME}")
    )


@pytest.mark.parametrize("failure", ["pull", "run"])
def test_failed_pull_or_migration_preserves_active_manifest(
    configured_app,
    image_manifest,
    docker_calls,
    monkeypatch,
    failure,
):
    original = (configured_app / MANIFEST_NAME).read_bytes()
    candidate = ReleaseImages.read(image_manifest).to_values()
    candidate[ImageField.BACKEND] = "ghcr.io/test/new@sha256:" + "b" * 64
    write_manifest(image_manifest, candidate)

    def run(self, *args):
        docker_calls.append(args)
        if args[0] == failure:
            raise RuntimeError("Docker failure")

    monkeypatch.setattr(ComposeProject, "run", run)
    with pytest.raises(RuntimeError):
        start(
            configured_app,
            "test-user",
            image_manifest=image_manifest,
            follow_logs=False,
        )
    assert (configured_app / MANIFEST_NAME).read_bytes() == original
    assert docker_calls[-1][0] == failure
    if failure == "pull":
        assert not any(call[0] == "stop" for call in docker_calls)


def test_rollback_checks_schema_and_follows_logs(configured_app, docker_calls):
    start(configured_app, "test-user", rollback=True)
    assert (
        "run",
        "--rm",
        "--no-deps",
        DeploymentService.MIGRATE,
        DeploymentService.CHECK,
    ) in docker_calls
    assert docker_calls[-1] == ("logs", "--follow", "--tail", str(LOG_TAIL_LINES))


def test_infrastructure_update_refused_before_docker(
    configured_app, image_manifest, docker_calls
):
    values = ReleaseImages.read(image_manifest).to_values()
    values[ImageField.POSTGRES] = "postgres:17@sha256:" + "b" * 64
    write_manifest(image_manifest, values)
    with pytest.raises(ValueError, match="maintenance"):
        start(configured_app, "test-user", image_manifest=image_manifest)
    assert docker_calls == []


def test_start_requires_private_manifest(configured_app, docker_calls):
    (configured_app / MANIFEST_NAME).chmod(0o644)
    with pytest.raises(ValueError, match="mode 600"):
        start(configured_app, "test-user")
    assert docker_calls == []


def test_concurrent_start_refused_before_docker(configured_app, docker_calls):
    with (configured_app / LOCK_NAME).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already running"):
            start(configured_app, "test-user")
    assert docker_calls == []


def test_successful_update_preserves_host_configuration(
    configured_app,
    image_manifest,
    docker_calls,
):
    manifest = configured_app / MANIFEST_NAME
    previous = dotenv_values(manifest, interpolate=False)
    images = ReleaseImages.read(image_manifest).to_values()
    images[ImageField.BACKEND] = "ghcr.io/test/new@sha256:" + "b" * 64
    write_manifest(image_manifest, images)
    secret = (
        configured_app / SECRETS_DIRECTORY_NAME / SecretFile.POSTGRES_PASSWORD
    ).read_bytes()
    start(configured_app, "test-user", image_manifest=image_manifest, follow_logs=False)
    active = dotenv_values(manifest, interpolate=False)
    assert active == {**previous, **images}
    assert (
        configured_app / SECRETS_DIRECTORY_NAME / SecretFile.POSTGRES_PASSWORD
    ).read_bytes() == secret
    assert stat.S_IMODE(manifest.stat().st_mode) == PRIVATE_FILE_MODE


def test_compose_uses_installed_file_and_ignores_ambient_images(tmp_path, monkeypatch):
    monkeypatch.setenv(ImageField.BACKEND, "unexpected:latest")
    installed = tmp_path / HOST_COMPOSE_NAME
    project = ComposeProject(
        tmp_path / MANIFEST_NAME, "polybot-test", compose_file=installed
    )
    command = project.command("config", "--quiet")
    assert command[command.index("-f") + 1] == str(installed)
    assert ImageField.BACKEND not in project.environment


def test_publish_builds_committed_context_and_records_registry_digests(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repo"
    repository.mkdir()
    for args in (
        ["init"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)
    (repository / "tracked").write_text("source")
    (repository / ".gitignore").write_text("secret\n")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    (repository / "secret").write_text("must not enter build context")
    monkeypatch.setattr(
        beta_publish, "clean_snapshot", lambda: source.clean_snapshot(repository)
    )
    monkeypatch.setattr(ghcr, "login", Mock())
    real_run = subprocess.run
    builds = []

    def run(command, **kwargs):
        if command[:3] == ["docker", "buildx", "build"]:
            builds.append(command)
            context = Path(command[-1])
            assert (context / "tracked").read_text() == "source"
            assert not (context / "secret").exists()
            assert command[command.index("--platform") + 1] == BuildPlatform.AMD64.value
            metadata = Path(command[command.index("--metadata-file") + 1])
            metadata.write_text(
                json.dumps({"containerimage.digest": "sha256:" + "b" * 64})
            )
            return subprocess.CompletedProcess(command, 0)
        if command[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"digest": "sha256:" + "c" * 64})
            )
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    output = tmp_path / "images.env"
    beta_publish.publish(
        "test",
        BuildPlatform.AMD64,
        output,
        DEFAULT_POSTGRES_IMAGE,
        DEFAULT_REDIS_IMAGE,
        "test",
    )
    values = ReleaseImages.read(output).to_values()
    assert len(builds) == 2
    assert (
        values[ImageField.BACKEND]
        == f"{ghcr.REGISTRY}/test/polybot-backend@sha256:" + "b" * 64
    )
    assert stat.S_IMODE(output.stat().st_mode) == PRIVATE_FILE_MODE
    (repository / "tracked").write_text("dirty")
    with pytest.raises(ValueError, match="commit repository"):
        beta_publish.publish(
            "test",
            BuildPlatform.AMD64,
            tmp_path / "other.env",
            DEFAULT_POSTGRES_IMAGE,
            DEFAULT_REDIS_IMAGE,
            "test",
        )
    assert len(builds) == 2


@pytest.mark.parametrize("failure", ["activation_record", "compose", "manifest"])
def test_interrupted_promotion_recovers_candidate_without_stale_activation(
    configured_app,
    image_manifest,
    docker_calls,
    monkeypatch,
    failure,
):

    app = configured_app.resolve()
    images = ReleaseImages.read(image_manifest).to_values()
    images[ImageField.BACKEND] = "ghcr.io/test/candidate@sha256:" + "b" * 64
    write_manifest(image_manifest, images)
    monkeypatch.setattr(
        beta_start, "compose_for_release", lambda commit: b"candidate compose"
    )
    activated = []
    monkeypatch.setattr(
        beta_start.BetaRelease,
        "activate",
        lambda self, **kwargs: activated.append(
            (self.settings.images.to_values(), kwargs)
        ),
    )
    real_write = state_module.write_private
    failed = False

    def fail_once(path, content, **kwargs):
        nonlocal failed
        should_fail = (
            (
                failure == "activation_record"
                and path == app / JOURNAL_NAME
                and json.loads(content)[JournalField.PHASE] == AttemptPhase.ACTIVATED
            )
            or (failure == "compose" and path == app / HOST_COMPOSE_NAME)
            or (failure == "manifest" and path == app / MANIFEST_NAME)
        )
        if should_fail and not failed:
            failed = True
            raise OSError("injected promotion failure")
        real_write(path, content, **kwargs)

    monkeypatch.setattr(state_module, "write_private", fail_once)
    with pytest.raises(OSError, match="injected"):
        start(
            app,
            "test-user",
            image_manifest=image_manifest,
            follow_logs=False,
            rollback=True,
        )
    assert failed and DeploymentState(app).pending() is not None
    start(app, "test-user", follow_logs=False)
    assert len(activated) == (2 if failure == "activation_record" else 1)
    assert all(
        values == images and options == {"rollback": True}
        for values, options in activated
    )
    assert ReleaseImages.read(app / MANIFEST_NAME).to_values() == images
    assert (app / HOST_COMPOSE_NAME).read_bytes() == b"candidate compose"
    assert DeploymentState(app).pending() is None


@pytest.mark.parametrize(
    "field,value",
    [
        (JournalField.DIRECTORY, "../escape"),
        (JournalField.DIRECTORY, "missing-attempt"),
        (JournalField.PHASE, "unknown"),
        (JournalField.ROLLBACK, "false"),
    ],
)
def test_malformed_pending_journal_blocks_docker(
    configured_app, docker_calls, field, value
):
    state = DeploymentState(configured_app)
    settings = RuntimeManifest.read(state.manifest)
    attempt = state.prepare(settings, state.compose_file.read_bytes(), rollback=False)
    record = attempt.to_record()
    record[field] = value
    write_private(state.journal, json.dumps(record).encode())
    with pytest.raises(ValueError, match=INVALID_JOURNAL_MESSAGE):
        start(configured_app, "test-user", follow_logs=False)
    assert docker_calls == []


def test_explicit_release_can_replace_failed_pending_attempt(
    configured_app,
    image_manifest,
    docker_calls,
    monkeypatch,
):

    images = ReleaseImages.read(image_manifest).to_values()
    images[ImageField.BACKEND] = "ghcr.io/test/failed@sha256:" + "b" * 64
    write_manifest(image_manifest, images)
    activation = Mock(side_effect=RuntimeError("failed migration"))
    monkeypatch.setattr(BetaRelease, "activate", activation)
    with pytest.raises(RuntimeError):
        start(
            configured_app,
            "test-user",
            image_manifest=image_manifest,
            follow_logs=False,
        )
    assert DeploymentState(configured_app).pending() is not None
    images[ImageField.BACKEND] = "ghcr.io/test/fixed@sha256:" + "c" * 64
    write_manifest(image_manifest, images)
    activation.side_effect = None
    start(configured_app, "test-user", image_manifest=image_manifest, follow_logs=False)
    assert ReleaseImages.read(configured_app / MANIFEST_NAME).to_values() == images
    assert DeploymentState(configured_app).pending() is None


def test_local_docker_rejection_precedes_login_and_mutation(
    configured_app, docker_calls, monkeypatch
):
    gate = Mock(side_effect=ValueError("remote Docker target"))
    monkeypatch.setattr(ComposeProject, "require_local_docker", gate)
    with pytest.raises(ValueError, match="remote Docker"):
        start(configured_app, "test-user", follow_logs=False)
    gate.assert_called_once()
    assert docker_calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        (SMTP_PORT_ENV, "not-a-port"),
        (SMTP_FROM_ENV, "invalid sender"),
        (SMTP_SECURITY_ENV, "local"),
    ],
)
def test_invalid_runtime_manifest_rejected_before_docker(
    configured_app, docker_calls, field, value
):
    manifest = configured_app / MANIFEST_NAME
    values = dotenv_values(manifest, interpolate=False)
    values[field] = value
    write_manifest(manifest, values)
    with pytest.raises(ValueError):
        start(configured_app, "test-user", follow_logs=False)
    assert docker_calls == []


def test_fifo_manifest_is_rejected_without_blocking(tmp_path):

    path = tmp_path / MANIFEST_NAME
    os.mkfifo(path, PRIVATE_FILE_MODE)
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; from scripts.deployment.images import ReleaseImages; ReleaseImages.read(Path(sys.argv[1]))",
            str(path),
        ],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert process.returncode != 0
    assert "must be a regular file" in process.stderr


def test_symlink_manifest_is_rejected_before_docker(configured_app, docker_calls):
    manifest = configured_app / MANIFEST_NAME
    saved = configured_app / "saved.env"
    manifest.rename(saved)
    manifest.symlink_to(saved)
    with pytest.raises((ValueError, OSError)):
        start(configured_app, "test-user", follow_logs=False)
    assert docker_calls == []


def test_setup_inputs_resolve_against_actual_compose(configured_app):

    if shutil.which("docker") is None:
        pytest.skip(
            "Docker Compose CLI is needed for the generated configuration contract"
        )
    version = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, check=False
    )
    if version.returncode:
        pytest.skip("Docker Compose plugin is not installed")
    project = ComposeProject(
        configured_app / MANIFEST_NAME,
        "polybot-config-test",
        compose_file=configured_app / HOST_COMPOSE_NAME,
    )
    config = json.loads(
        subprocess.check_output(
            project.command("config", "--format", "json"),
            env=project.environment,
            text=True,
        )
    )
    assert set(config["secrets"]) == {secret.value for secret in SecretFile}
    for secret in config["secrets"].values():
        assert read_regular(Path(secret["file"]))
    images = ReleaseImages.read(configured_app / MANIFEST_NAME)
    services = config["services"]
    for field, service in (
        (ImageField.BACKEND, DeploymentService.API),
        (ImageField.FRONTEND, ENTRYPOINT_SERVICE),
        (ImageField.POSTGRES, POSTGRES_SERVICE),
        (ImageField.REDIS, REDIS_SERVICE),
    ):
        assert services[service]["image"] == str(images.references[field])
    assert services[ENTRYPOINT_SERVICE]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services[DeploymentService.API]["environment"][BOT_MODE_ENV] == BotMode.PAPER
    connection = urlsplit(
        (configured_app / SECRETS_DIRECTORY_NAME / SecretFile.DATABASE_URL).read_text()
    )
    postgres = services[POSTGRES_SERVICE]
    assert (
        connection.username
        == postgres["environment"]["POSTGRES_USER"]
        == storage.POSTGRES_USER
    )
    assert (
        connection.path.removeprefix("/")
        == postgres["environment"]["POSTGRES_DB"]
        == storage.POSTGRES_DATABASE
    )
    assert (
        connection.hostname == POSTGRES_SERVICE
        and connection.port == storage.POSTGRES_PORT
    )
    redis = urlsplit(
        (configured_app / SECRETS_DIRECTORY_NAME / SecretFile.REDIS_URL).read_text()
    )
    assert redis.hostname == REDIS_SERVICE and redis.port == storage.REDIS_PORT
    assert redis.path == f"/{storage.REDIS_DATABASE}"


def test_compose_provenance_uses_selected_commit_not_worktree(tmp_path):

    repository = tmp_path / "repository"
    repository.mkdir()
    for args in (
        ["init"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True)
    compose = repository / SOURCE_COMPOSE_PATH
    compose.parent.mkdir()
    compose.write_bytes(b"committed compose")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    compose.write_bytes(b"dirty worktree compose")
    assert (
        source.compose_for_release(commit, repository=repository)
        == b"committed compose"
    )


@pytest.mark.parametrize("kind", ["existing", "symlink"])
def test_publish_does_not_touch_existing_output(tmp_path, monkeypatch, kind):
    output = tmp_path / "images.env"
    if kind == "existing":
        output.write_text("retained release")
    else:
        output.symlink_to(tmp_path / "missing")
    snapshot = Mock(side_effect=AssertionError("build must not start"))
    monkeypatch.setattr(beta_publish, "clean_snapshot", snapshot)
    with pytest.raises(ValueError, match="output already exists"):
        beta_publish.publish(
            "test",
            BuildPlatform.AMD64,
            output,
            DEFAULT_POSTGRES_IMAGE,
            DEFAULT_REDIS_IMAGE,
            "test",
        )
    snapshot.assert_not_called()
    assert (
        output.is_symlink()
        if kind == "symlink"
        else output.read_text() == "retained release"
    )


@pytest.mark.parametrize(
    "metadata", ["{}", '{"digest": null}', '{"digest": "sha256:invalid"}', "not-json"]
)
def test_buildx_invalid_metadata_is_rejected(metadata):

    with pytest.raises(ValueError, match="Buildx did not return"):
        reference_from_metadata("ghcr.io/test/image", metadata, "digest")


def test_second_image_failure_produces_no_release_manifest(tmp_path, monkeypatch):

    @contextmanager
    def snapshot():
        yield SourceSnapshot("a" * 40, tmp_path)

    pinned = ImageReference.parse(
        "ghcr.io/test/image@sha256:" + "a" * 64, policy=ImagePolicy.REGISTRY
    )
    monkeypatch.setattr(beta_publish, "clean_snapshot", snapshot)
    monkeypatch.setattr(ghcr, "login", Mock())
    monkeypatch.setattr(beta_publish, "resolve_image", lambda image: pinned)
    build = Mock(side_effect=[pinned, RuntimeError("frontend build failed")])
    monkeypatch.setattr(beta_publish, "build_image", build)
    output = tmp_path / "images.env"
    with pytest.raises(RuntimeError, match="frontend"):
        beta_publish.publish(
            "test",
            BuildPlatform.AMD64,
            output,
            DEFAULT_POSTGRES_IMAGE,
            DEFAULT_REDIS_IMAGE,
            "test",
        )
    assert build.call_count == 2 and not output.exists()


def test_atomic_manifest_creation_does_not_clobber_concurrent_writer(tmp_path):
    path = tmp_path / MANIFEST_NAME
    path.write_text("retained")
    with pytest.raises(FileExistsError):
        write_manifest(path, {"SETTING": "new"}, replace=False)
    assert path.read_text() == "retained"


@pytest.mark.parametrize("kind", ["tls_certificate", "tls_key", "lock"])
def test_nonregular_setup_and_lock_inputs_do_not_block(tmp_path, kind):
    regular = tmp_path / "regular.pem"
    regular.write_text("unused until both TLS files pass ingress")
    fifo = tmp_path / (LOCK_NAME if kind == "lock" else "input.pem")
    os.mkfifo(fifo, PRIVATE_FILE_MODE)
    program = (
        "from pathlib import Path; import sys; "
        "from scripts.deployment.tls import TlsMaterial; "
        "from scripts.deployment.state import DeploymentState; "
    )
    if kind == "lock":
        program += "\nwith DeploymentState(Path(sys.argv[1])).locked(): pass"
        arguments = [str(tmp_path)]
    else:
        program += "TlsMaterial.from_paths(Path(sys.argv[1]), Path(sys.argv[2]))"
        arguments = (
            [str(fifo), str(regular)]
            if kind == "tls_certificate"
            else [str(regular), str(fifo)]
        )
    result = subprocess.run(
        [sys.executable, "-c", program, *arguments],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode != 0
    assert "must be a regular file" in result.stderr


@pytest.mark.parametrize(
    "repository",
    [
        "ghcr.io/acme/Backend",
        "ghcr.io/acme//backend",
        "ghcr.io/acme/backend:tag:other",
    ],
)
def test_image_ingress_rejects_invalid_repository_syntax(repository):
    with pytest.raises(ValueError, match="invalid image repository"):
        ImageReference.parse(
            f"{repository}@sha256:" + "a" * 64, policy=ImagePolicy.REGISTRY
        )


@pytest.mark.parametrize(
    "repository",
    ["ghcr.io/acme/backend", "localhost:5000/team/image:Tag_1", "library/image__name"],
)
def test_image_ingress_accepts_registry_paths_and_tags(repository):
    value = f"{repository}@sha256:" + "a" * 64
    assert str(ImageReference.parse(value, policy=ImagePolicy.REGISTRY)) == value


def test_manual_release_passes_canonical_values_to_compose(configured_app):
    manifest = configured_app / MANIFEST_NAME
    values = dotenv_values(manifest, interpolate=False)
    values[HTTPS_PORT_ENV] = f"+{DEFAULT_HTTPS_PORT}"
    values[DOCKER_HOST_ENV] = "tcp://must-not-export:2375"
    write_manifest(manifest, values)
    release = BetaRelease.from_manifest(
        manifest, "canonical-values", compose_file=configured_app / HOST_COMPOSE_NAME
    )
    assert release.compose.environment[HTTPS_PORT_ENV] == str(DEFAULT_HTTPS_PORT)
    assert release.compose.environment.get(DOCKER_HOST_ENV) != values[DOCKER_HOST_ENV]
    if shutil.which("docker"):
        subprocess.run(
            release.compose.command("config", "--quiet"),
            env=release.compose.environment,
            check=True,
        )


@pytest.mark.parametrize(
    "origin,allow_http,port",
    [
        ("https://example.com", False, 443),
        ("http://localhost", True, 80),
        (DEFAULT_AUTH_ORIGIN, False, DEFAULT_HTTPS_PORT),
    ],
)
def test_origin_exposes_effective_port(origin, allow_http, port):
    assert AuthSettings(origin, allow_http=allow_http).port == port


def test_setup_rejects_local_smtp_before_installation(
    tmp_path, image_manifest, certificate
):
    cert, key = certificate
    smtp = SmtpSettings(
        host="localhost",
        port=1025,
        sender="test@example.com",
        security=SmtpSecurity.LOCAL,
        allow_local=True,
        username=SecretStr("user"),
        password=SecretStr("password"),
    )
    app = tmp_path / "app"
    with pytest.raises(ValueError, match="TLS SMTP"):
        beta_setup.setup(app, image_manifest, DEFAULT_AUTH_ORIGIN, smtp, cert, key)
    assert not app.exists()


def test_pending_forward_attempt_cannot_silently_become_rollback(
    configured_app, docker_calls
):
    state = DeploymentState(configured_app)
    settings = RuntimeManifest.read(state.manifest)
    attempt = state.prepare(settings, state.compose_file.read_bytes(), rollback=False)
    state.begin_activation(attempt)
    with pytest.raises(ValueError, match="forward migration"):
        start(configured_app, "test-user", follow_logs=False, rollback=True)
    assert state.pending() == attempt
    assert docker_calls == []


def test_completed_pending_release_promotes_before_explicit_replacement(
    configured_app, image_manifest, docker_calls, monkeypatch
):
    state = DeploymentState(configured_app)
    settings = RuntimeManifest.read(state.manifest)
    attempt = state.prepare(settings, state.compose_file.read_bytes(), rollback=False)
    state.mark_activated(attempt)
    images = ReleaseImages.read(image_manifest).to_values()
    images[ImageField.BACKEND] = "ghcr.io/test/replacement@sha256:" + "c" * 64
    write_manifest(image_manifest, images)
    activations = []

    def record_activation(self, **kwargs):
        assert ReleaseImages.read(state.manifest) == settings.images
        activations.append(self.settings.images.to_values())

    monkeypatch.setattr(BetaRelease, "activate", record_activation)
    start(configured_app, "test-user", image_manifest=image_manifest, follow_logs=False)
    assert activations == [images]
    assert ReleaseImages.read(state.manifest).to_values() == images
    assert state.pending() is None


def test_recovery_rejects_symlinked_history_before_promotion(
    configured_app, docker_calls
):
    state = DeploymentState(configured_app)
    settings = RuntimeManifest.read(state.manifest)
    previous_manifest = state.manifest.read_bytes()
    previous_compose = state.compose_file.read_bytes()
    attempt = state.prepare(settings, b"external candidate", rollback=False)
    state.mark_activated(attempt)
    external = state.directory.parent / "external-history"
    state.history.rename(external)
    state.history.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="history must be a real directory"):
        start(configured_app, "test-user", follow_logs=False)
    assert docker_calls == []
    assert state.manifest.read_bytes() == previous_manifest
    assert state.compose_file.read_bytes() == previous_compose
    assert state.journal.exists()
