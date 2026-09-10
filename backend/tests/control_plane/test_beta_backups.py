"""Archive integrity, bounded processes and fail-closed restore boundaries."""

import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from api.lifecycle.policy import (
    BACKUP_RETENTION_DAYS,
    RECOVERY_POINT_HOURS,
    RECOVERY_TIME_HOURS,
)

from scripts.beta_backup.archive_name import (
    ArchiveName,
    ARCHIVE_CHECKSUM_ALGORITHM,
    ARCHIVE_CHECKSUM_HEX_LENGTH,
    BACKUP_ARCHIVE_PREFIX,
    BACKUP_ARCHIVE_SUFFIX,
)
from scripts.beta_backup.archives import BackupArchives
from scripts.beta_backup.backup import BetaBackup
from scripts.beta_backup.database import ComposeDatabase
from scripts.beta_backup.policy import AGE_BINARY, BACKUP_PROCESS_TIMEOUT_SECONDS
from scripts.beta_backup.restore import BetaRestore
from scripts.beta_backup.restore.destination import RestoreDestination
from scripts.beta_release import DOCKER_CONTEXT_ENV, DOCKER_HOST_ENV, BetaRelease


def archive(directory, created):
    content = b"encrypted fixture"
    path = (
        directory
        / ArchiveName(
            created,
            uuid4(),
            hashlib.new(ARCHIVE_CHECKSUM_ALGORITHM, content).hexdigest(),
        ).format()
    )
    path.write_bytes(content)
    return path


@pytest.fixture
def restore_inputs(tmp_path):
    tmp_path.chmod(0o700)
    identity = tmp_path / "identity"
    identity.write_text("fixture")
    identity.chmod(0o600)
    return (
        tmp_path / "manifest",
        archive(tmp_path, datetime.now(timezone.utc)),
        identity,
        tmp_path,
    )


def test_only_completed_intact_archives_count_toward_retention_and_rpo(tmp_path):
    tmp_path.chmod(0o700)
    now = datetime.now(timezone.utc)
    old = archive(tmp_path, now - timedelta(days=BACKUP_RETENTION_DAYS, seconds=1))
    recent = archive(tmp_path, now - timedelta(hours=RECOVERY_POINT_HOURS, seconds=-1))
    future = archive(tmp_path, now + timedelta(hours=1))
    partial = tmp_path / ".incomplete-fixture"
    partial.write_bytes(b"partial")
    archives = BackupArchives(tmp_path)
    archives.expire()
    assert not old.exists()
    assert recent.exists() and partial.exists()
    archives.require_recent()
    recent.write_bytes(b"truncated or corrupted")
    with pytest.raises(RuntimeError):
        archives.require_recent()
    assert future.exists()


def test_backup_rejects_shared_destination(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError):
        BackupArchives(tmp_path)


@pytest.mark.parametrize("input_index", [2, 3])
def test_restore_rejects_insecure_identity_or_scratch(restore_inputs, input_index):
    restore_inputs[input_index].chmod(0o755)
    with pytest.raises(ValueError):
        BetaRestore(*restore_inputs)


@pytest.mark.parametrize("dump_status,encryption_status", [(1, 0), (0, 1)])
def test_failed_pipeline_publishes_nothing_and_removes_partial(
    tmp_path, dump_status, encryption_status
):
    tmp_path.chmod(0o700)
    recipients = tmp_path / "recipients"
    recipients.write_text("fixture")
    dump, encrypt = MagicMock(), MagicMock()
    dump.poll.return_value = None
    dump.wait.return_value = dump_status
    encrypt.wait.return_value = encryption_status
    with patch(
        "scripts.beta_backup.backup.pipeline.subprocess.Popen",
        side_effect=[dump, encrypt],
    ):
        with pytest.raises(RuntimeError):
            BetaBackup(MagicMock(), tmp_path, recipients).create()
    dump.kill.assert_called_once()
    assert dump.wait.call_count >= 2
    encrypt.wait.assert_called_once()
    assert list(tmp_path.iterdir()) == [recipients]


def test_pipeline_timeout_reaps_live_children_and_removes_partial(tmp_path):
    tmp_path.chmod(0o700)
    recipients = tmp_path / "recipients"
    recipients.write_text("fixture")
    dump, encrypt = MagicMock(), MagicMock()
    dump.poll.return_value = encrypt.poll.return_value = None
    encrypt.wait.side_effect = [
        subprocess.TimeoutExpired(AGE_BINARY, BACKUP_PROCESS_TIMEOUT_SECONDS),
        0,
    ]
    with patch(
        "scripts.beta_backup.backup.pipeline.subprocess.Popen",
        side_effect=[dump, encrypt],
    ):
        with pytest.raises(subprocess.TimeoutExpired):
            BetaBackup(MagicMock(), tmp_path, recipients).create()
    for process in (dump, encrypt):
        process.kill.assert_called_once()
        assert process.wait.called
    assert list(tmp_path.iterdir()) == [recipients]


def test_decryption_failure_never_prepares_or_mutates_database(restore_inputs):
    with (
        patch("scripts.beta_backup.restore.BetaRelease"),
        patch("scripts.beta_backup.restore.ComposeDatabase") as database,
        patch("scripts.beta_backup.restore.RestoreDestination") as destination,
        patch(
            "scripts.beta_backup.restore.decrypt.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, [AGE_BINARY]),
        ),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            BetaRestore(*restore_inputs).restore()
        destination.return_value.prepare.assert_not_called()
        database.return_value.restore.assert_not_called()
        destination.return_value.quarantine.assert_not_called()
    assert not any(path.name.startswith("tmp") for path in restore_inputs[3].iterdir())


def test_existing_restore_destination_never_starts_services():
    release = MagicMock()
    with patch(
        "scripts.beta_backup.restore.destination.subprocess.check_output",
        return_value=b"existing-container",
    ):
        with pytest.raises(ValueError):
            RestoreDestination(release).prepare()
    release.compose.assert_not_called()


@pytest.mark.parametrize(
    "elapsed_seconds", [RECOVERY_TIME_HOURS * 3600, RECOVERY_TIME_HOURS * 3600 + 1]
)
def test_restore_time_target_is_enforced_without_reopening(
    restore_inputs, elapsed_seconds
):
    with (
        patch("scripts.beta_backup.restore.BetaRelease") as release,
        patch("scripts.beta_backup.restore.ComposeDatabase"),
        patch("scripts.beta_backup.restore.RestoreDestination") as destination,
        patch("scripts.beta_backup.restore.decrypt.subprocess.run"),
        patch(
            "scripts.beta_backup.restore.monotonic", side_effect=[0, elapsed_seconds]
        ),
    ):
        restore = BetaRestore(*restore_inputs)
        if elapsed_seconds > RECOVERY_TIME_HOURS * 3600:
            with pytest.raises(RuntimeError):
                restore.restore()
        else:
            assert restore.restore() == (restore.project, elapsed_seconds)
        destination.return_value.quarantine.assert_called_once()
        release.return_value.activate.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["database", "quarantine"])
def test_restore_failure_after_preparation_never_claims_success(
    restore_inputs, failure_stage
):
    with (
        patch("scripts.beta_backup.restore.BetaRelease") as release,
        patch("scripts.beta_backup.restore.ComposeDatabase") as database,
        patch("scripts.beta_backup.restore.RestoreDestination") as destination,
        patch("scripts.beta_backup.restore.decrypt.subprocess.run"),
    ):
        if failure_stage == "database":
            database.return_value.restore.side_effect = RuntimeError("restore failed")
        else:
            destination.return_value.quarantine.side_effect = RuntimeError(
                "quarantine failed"
            )
        with pytest.raises(RuntimeError):
            BetaRestore(*restore_inputs).restore()
        destination.return_value.prepare.assert_called_once()
        if failure_stage == "database":
            destination.return_value.quarantine.assert_not_called()
        release.return_value.activate.assert_not_called()
    assert not any(path.name.startswith("tmp") for path in restore_inputs[3].iterdir())


@pytest.mark.parametrize("override", [DOCKER_HOST_ENV, DOCKER_CONTEXT_ENV])
def test_backup_target_rejects_ambient_docker_overrides(monkeypatch, override):
    monkeypatch.setenv(override, "unintended-target")
    release = object.__new__(BetaRelease)
    with pytest.raises(ValueError):
        release.require_local_docker()


def test_backup_target_rejects_remote_context_and_pins_local_socket(monkeypatch):
    monkeypatch.delenv(DOCKER_HOST_ENV, raising=False)
    monkeypatch.delenv(DOCKER_CONTEXT_ENV, raising=False)
    release = object.__new__(BetaRelease)
    release._docker_host = None
    with patch(
        "scripts.beta_release.subprocess.check_output",
        return_value="ssh://unintended-host",
    ):
        with pytest.raises(ValueError):
            release.require_local_docker()
    with patch(
        "scripts.beta_release.subprocess.check_output",
        return_value="unix:///fixture/docker.sock",
    ):
        release.require_local_docker()
    assert release._docker_host == "unix:///fixture/docker.sock"


def test_encryption_start_failure_reaps_dump_and_removes_partial(tmp_path):
    tmp_path.chmod(0o700)
    recipients = tmp_path / "recipients"
    recipients.write_text("fixture")
    dump = MagicMock()
    dump.poll.return_value = None
    with patch(
        "scripts.beta_backup.backup.pipeline.subprocess.Popen",
        side_effect=[dump, OSError("age unavailable")],
    ):
        with pytest.raises(OSError):
            BetaBackup(MagicMock(), tmp_path, recipients).create()
    dump.kill.assert_called_once()
    dump.wait.assert_called_once()
    assert list(tmp_path.iterdir()) == [recipients]


def test_archive_parser_and_discovery_ignore_noncanonical_or_nonfile_entries(tmp_path):
    tmp_path.chmod(0o700)
    now = datetime.now(timezone.utc)
    canonical = archive(tmp_path, now)
    name = ArchiveName.parse(canonical.name)
    assert name is not None
    malformed = [
        "unrelated.dump.age",
        canonical.name + ".partial",
        f"{BACKUP_ARCHIVE_PREFIX}invalid-time-{name.identifier.hex}-{name.checksum}{BACKUP_ARCHIVE_SUFFIX}",
        canonical.name.replace(name.identifier.hex, "invalid-uuid"),
        canonical.name.replace(name.checksum, "G" * ARCHIVE_CHECKSUM_HEX_LENGTH),
        canonical.name.replace(name.checksum, name.checksum[:-1]),
    ]
    for filename in malformed:
        (tmp_path / filename).write_bytes(b"invalid")
        assert ArchiveName.parse(filename) is None
    canonical.unlink()
    target = tmp_path / "target"
    target.write_bytes(b"fixture")
    canonical.symlink_to(target)
    directory = tmp_path / ArchiveName(now, uuid4(), name.checksum).format()
    directory.mkdir()
    archives = BackupArchives(tmp_path)
    with pytest.raises(RuntimeError):
        archives.require_recent()
    archives.expire()
    assert canonical.is_symlink() and directory.is_dir()
    assert all((tmp_path / filename).exists() for filename in malformed)
    archive(tmp_path, now)
    archives.require_recent()


def test_verified_docker_endpoint_is_pinned_on_dump_and_restore_commands(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(DOCKER_HOST_ENV, raising=False)
    monkeypatch.delenv(DOCKER_CONTEXT_ENV, raising=False)
    release = object.__new__(BetaRelease)
    release._docker_host = None
    release.project = "isolated-backup-test"
    release.manifest = tmp_path / "manifest"
    socket = "unix:///fixture/docker.sock"
    with patch("scripts.beta_release.subprocess.check_output", return_value=socket):
        database = ComposeDatabase(release)
    monkeypatch.setenv(DOCKER_HOST_ENV, "ssh://later-host")
    monkeypatch.setenv(DOCKER_CONTEXT_ENV, "later-context")
    assert database.dump_command()[:4] == ["docker", "--host", socket, "compose"]
    with patch("scripts.beta_backup.database.subprocess.run") as run:
        database.restore(MagicMock())
    assert run.call_args.args[0][:4] == ["docker", "--host", socket, "compose"]
    environment = run.call_args.kwargs["env"]
    assert DOCKER_HOST_ENV not in environment and DOCKER_CONTEXT_ENV not in environment
