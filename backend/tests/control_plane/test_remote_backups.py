"""Real SFTP transfer, host-key and retention boundaries; no external account."""

import hashlib
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from api.lifecycle.policy import BACKUP_RETENTION_DAYS, RECOVERY_POINT_HOURS

from control_plane.sftp_fixture import sftp_server
from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.remote import RemoteBackups


def snapshot(directory, *, days=0):
    content = b"encrypted fixture bytes"
    name = ArchiveName(
        datetime.now(UTC) - timedelta(days=days),
        uuid4(),
        hashlib.sha256(content).hexdigest(),
    ).format()
    path = directory / name
    path.write_bytes(content)
    bundle = directory / "bundle.tar.gz"
    bundle.write_bytes(b"non-secret matching release fixture")
    return path, bundle


def test_real_sftp_upload_readback_download_corruption_and_retention(tmp_path):
    with sftp_server(tmp_path) as (remote, storage, _process):
        archive, bundle = snapshot(tmp_path)
        name = archive.name
        remote.upload(archive, bundle)
        assert not archive.exists()
        remote.require_recent()
        download = tmp_path / "download"
        download.mkdir(mode=0o700)
        restored, retained_bundle = remote.download(name, download)
        assert restored.read_bytes() == b"encrypted fixture bytes"
        assert retained_bundle.read_bytes() == bundle.read_bytes()
        (storage / name).write_bytes(b"corrupt remote archive")
        with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
            remote.require_recent()
        unrelated = storage / "do-not-delete.txt"
        unrelated.write_text("retain")
        expired, _ = snapshot(tmp_path, days=BACKUP_RETENTION_DAYS + 1)
        (storage / expired.name).write_bytes(expired.read_bytes())
        partial = storage / (expired.name + ".abcdef12.partial")
        partial.write_bytes(b"interrupted")
        remote.expire()
        assert not partial.exists()
        assert not (storage / expired.name).exists()
        assert unrelated.exists()


def test_wrong_host_key_and_unavailable_storage_never_count_as_backup(tmp_path):
    with sftp_server(tmp_path) as (remote, storage, process):
        archive, bundle = snapshot(tmp_path)
        known = tmp_path / "known_hosts"
        original = known.read_text()
        known.write_text(
            original.split(" ")[0] + " " + (tmp_path / "client.pub").read_text()
        )
        with pytest.raises(subprocess.CalledProcessError):
            remote.upload(archive, bundle)
        assert archive.exists() and not list(storage.iterdir())
        known.write_text(original)
        process.terminate()
        process.wait(timeout=10)
        with pytest.raises(subprocess.CalledProcessError):
            remote.upload(archive, bundle)
        assert archive.exists()


def test_partial_upload_and_corrupt_bundle_do_not_satisfy_rpo(tmp_path):
    with sftp_server(tmp_path) as (remote, storage, _process):
        archive, bundle = snapshot(tmp_path)
        (storage / archive.name).write_bytes(archive.read_bytes())
        with pytest.raises(RuntimeError):
            remote.require_recent()
        bundle_name = f"{archive.name}.{hashlib.sha256(bundle.read_bytes()).hexdigest()}.release.tar.gz"
        (storage / bundle_name).write_bytes(b"partial")
        with pytest.raises(RuntimeError):
            remote.require_recent()
        (storage / bundle_name).write_bytes(bundle.read_bytes())
        (storage / archive.name).write_bytes(b"interrupted upload")
        with pytest.raises(RuntimeError):
            remote.require_recent()


def test_stale_snapshot_and_explicit_host_key_requirement(tmp_path):
    with sftp_server(tmp_path) as (remote, _storage, _process):
        archive, bundle = snapshot(tmp_path, days=RECOVERY_POINT_HOURS / 24 + 1)
        remote.upload(archive, bundle)
        with pytest.raises(RuntimeError):
            remote.require_recent()
        config = tmp_path / "rclone.conf"
        config.write_text(
            config.read_text().replace(str(tmp_path / "known_hosts"), "none")
        )
        with pytest.raises(ValueError, match="known_hosts"):
            RemoteBackups(config, "backup:/polybot", tmp_path)
