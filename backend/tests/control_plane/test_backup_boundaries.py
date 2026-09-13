"""Transfer and recovery preparation failure paths preserve owned artifacts."""

import os
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from api.lifecycle.policy import BACKUP_INTERVAL_HOURS
from polybot.persistence.hashing import sha256_file

from control_plane.test_remote_backups import snapshot
from scripts.beta_backup.__main__ import main as backup_main
from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.archives import BackupArchives
from scripts.beta_backup.commands import BackupCommand
from scripts.beta_backup.policy import MAX_RETAINED_STAGING_ARCHIVES
from scripts.beta_backup.remote import RemoteBackups
from scripts.beta_backup.remote.artifacts import ReleaseBundleName, RemoteBackupPair
from scripts.beta_backup.remote.config import SftpApplicationDirectory, SftpRemoteConfig
from scripts.beta_backup.remote.transport import RemoteBackupError, RemoteEntry
from scripts.private_files import write_private


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        [1],
        [{"Name": "a", "IsDir": "false"}],
        [{"Name": "../outside", "IsDir": False}],
        [{"Name": "a", "IsDir": False}, {"Name": "a", "IsDir": False}],
    ],
)
def test_rclone_listing_ingress_rejects_ambiguous_or_unsafe_records(record):
    with pytest.raises((ValueError, RemoteBackupError)):
        RemoteEntry.parse_listing(record)


@pytest.mark.parametrize(
    "directory",
    [
        "backup:/",
        "other:/polybot",
        "backup:/home",
        "backup:/backups",
        "backup:relative",
        "backup:/a/../b",
    ],
)
def test_remote_directory_scope_is_dedicated(directory):
    with pytest.raises(ValueError):
        SftpApplicationDirectory.from_remote(directory)


@pytest.mark.parametrize(
    "change", ["backend", "ssh", "tofu", "missing_key", "bad_section"]
)
def test_rclone_config_requires_explicit_sftp_host_verification(tmp_path, change):
    tmp_path.chmod(0o700)
    known = tmp_path / "known_hosts"
    write_private(known, b"fixture")
    contents = f"[backup]\ntype=sftp\nknown_hosts_file={known}\n"
    if change == "backend":
        contents = contents.replace("type=sftp", "type=local")
    if change == "ssh":
        contents += "ssh=untrusted-command\n"
    if change == "tofu":
        contents += "pin_host_key=true\n"
    if change == "missing_key":
        known.unlink()
    if change == "bad_section":
        contents = "[unknown]\ntype=sftp\n"
    config = tmp_path / "rclone.conf"
    write_private(config, contents.encode())
    with pytest.raises((ValueError, OSError)):
        SftpRemoteConfig.read(config, "backup:/polybot", tmp_path)


@pytest.mark.parametrize(
    "failure",
    [
        "provenance",
        "invalid_bundle",
        "bundle_readback",
        "archive_readback",
        "archive_checksum",
    ],
)
def test_upload_validation_and_each_readback_failure_preserve_local_archive(
    tmp_path, failure
):
    archive, bundle = snapshot(tmp_path)
    remote = object.__new__(RemoteBackups)
    remote.transport = Mock()
    remote.inventory = Mock()
    remote.transport.checksum.side_effect = (
        ["wrong"] if failure == "bundle_readback" else [sha256_file(bundle), "wrong"]
    )
    if failure == "archive_checksum":
        archive.write_bytes(b"modified")
    if failure == "invalid_bundle":
        bundle.write_bytes(b"not a bundle")
    with pytest.raises((ValueError, RuntimeError, tarfile.TarError)):
        remote.upload(
            archive,
            bundle,
            source_commit=("b" if failure == "provenance" else "a") * 40,
        )
    assert archive.exists()
    remote.inventory.expire.assert_not_called()
    if failure in {"provenance", "invalid_bundle", "archive_checksum"}:
        remote.transport.run.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        "archive_copy",
        "bundle_copy",
        "archive_checksum",
        "bundle_checksum",
        "invalid_bundle",
    ],
)
def test_failed_download_cleans_both_owned_artifacts(tmp_path, failure):
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    archive, bundle = snapshot(source)
    if failure == "invalid_bundle":
        bundle.write_bytes(b"invalid but matching hash")
    pair = RemoteBackupPair(
        ArchiveName.parse(archive.name),
        ReleaseBundleName(ArchiveName.parse(archive.name), sha256_file(bundle)),
    )
    remote = object.__new__(RemoteBackups)
    remote.inventory = Mock()
    remote.inventory.completed_pairs.return_value = [pair]
    remote.transport = Mock()
    remote.transport.remote_artifact_path.side_effect = lambda name: name

    def copy(command, name, destination):
        is_archive = name == archive.name
        if failure == ("archive_copy" if is_archive else "bundle_copy"):
            Path(destination).write_bytes(b"partial")
            raise RemoteBackupError("failed copy")
        data = (archive if is_archive else bundle).read_bytes()
        if failure == ("archive_checksum" if is_archive else "bundle_checksum"):
            data = b"corrupt"
        Path(destination).write_bytes(data)

    remote.transport.run.side_effect = copy
    destination = tmp_path / "download"
    destination.mkdir(mode=0o700)
    with pytest.raises((RuntimeError, tarfile.TarError)):
        remote.download(archive.name, destination)
    assert not list(destination.iterdir())


@pytest.mark.parametrize("failure", ["ambiguous", "existing"])
def test_download_rejects_ambiguous_pair_or_existing_destination(tmp_path, failure):
    tmp_path.chmod(0o700)
    archive, bundle = snapshot(tmp_path)
    pair = RemoteBackupPair(
        ArchiveName.parse(archive.name),
        ReleaseBundleName(ArchiveName.parse(archive.name), sha256_file(bundle)),
    )
    remote = object.__new__(RemoteBackups)
    remote.inventory = Mock()
    remote.inventory.completed_pairs.return_value = (
        [pair, pair] if failure == "ambiguous" else [pair]
    )
    remote.transport = Mock()
    with pytest.raises(ValueError):
        remote.download(archive.name, tmp_path)
    remote.transport.run.assert_not_called()


def test_future_recovery_point_is_not_fresh(tmp_path):
    archive, bundle = snapshot(tmp_path, days=-1)
    pair = RemoteBackupPair(
        ArchiveName.parse(archive.name),
        ReleaseBundleName(ArchiveName.parse(archive.name), sha256_file(bundle)),
    )
    remote = object.__new__(RemoteBackups)
    remote.inventory = Mock()
    remote.inventory.completed_pairs.return_value = [pair]
    with pytest.raises(RemoteBackupError):
        remote.require_recent()
    remote.inventory.is_intact.assert_not_called()


@pytest.mark.parametrize("fail_extract", [False, True])
def test_download_command_extracts_verified_source_or_cleans_failure(
    tmp_path, monkeypatch, capsys, fail_extract
):
    archive, bundle = snapshot(tmp_path)
    monkeypatch.setattr(
        "scripts.beta_backup.__main__.RemoteBackups",
        lambda *args: Mock(download=Mock(return_value=(archive, bundle))),
    )
    if fail_extract:
        monkeypatch.setattr(
            tarfile.TarFile,
            "extractall",
            Mock(side_effect=tarfile.ExtractError("fixture")),
        )
    monkeypatch.setattr(
        "sys.argv",
        [
            "backup",
            BackupCommand.DOWNLOAD,
            archive.name,
            "--directory",
            str(tmp_path),
            "--config",
            str(tmp_path / "rclone.conf"),
            "--remote",
            "backup:/polybot",
        ],
    )
    if fail_extract:
        with pytest.raises(SystemExit) as failure:
            backup_main()
        assert failure.value.code == 1
        assert (
            not archive.exists()
            and not bundle.exists()
            and not (tmp_path / "release").exists()
        )
    else:
        backup_main()
        assert (tmp_path / "release" / "README.md").exists()
        assert "Verified" in capsys.readouterr().out


def test_staging_prunes_only_bounded_owned_archives_and_stale_regular_partials(
    tmp_path,
):
    tmp_path.chmod(0o700)
    for age in range(MAX_RETAINED_STAGING_ARCHIVES + 2):
        snapshot(tmp_path, days=age)
    incomplete = tmp_path / ".incomplete-stale"
    incomplete.write_bytes(b"partial")
    past = (datetime.now(UTC) - timedelta(hours=BACKUP_INTERVAL_HOURS + 1)).timestamp()
    os.utime(incomplete, (past, past))
    recent = tmp_path / ".incomplete-recent"
    recent.write_bytes(b"partial")
    symlink = tmp_path / ".incomplete-link"
    symlink.symlink_to(recent)
    BackupArchives(tmp_path).prune_staging()
    assert (
        sum(ArchiveName.parse(path.name) is not None for path in tmp_path.iterdir())
        == MAX_RETAINED_STAGING_ARCHIVES
    )
    assert not incomplete.exists()
    assert recent.exists() and symlink.is_symlink()
