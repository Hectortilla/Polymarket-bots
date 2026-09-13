"""Verified off-server archives through rclone's host-key-checked SFTP backend."""

import configparser
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from api.lifecycle.policy import BACKUP_RETENTION_DAYS, RECOVERY_POINT_HOURS
from polybot.persistence.hashing import sha256_file

from scripts.beta_backup.archive_name import ArchiveName
from scripts.beta_backup.paths import PrivateBackupPath
from scripts.beta_backup.policy import BACKUP_PROCESS_TIMEOUT_SECONDS


class RemoteBackups:
    def __init__(self, config: Path, remote: str, staging: Path) -> None:
        self.config = PrivateBackupPath.file(config)
        self.staging = PrivateBackupPath.directory(staging)
        if re.fullmatch(r"backup:/[a-zA-Z0-9/_-]+", remote) is None or remote.rstrip(
            "/"
        ) in {"backup:", "backup:/", "backup:/backups", "backup:/home"}:
            raise ValueError(
                "a dedicated absolute SFTP application directory is required"
            )
        self.remote = remote.rstrip("/")
        settings = configparser.ConfigParser(interpolation=None)
        settings.read(self.config)
        section = settings["backup"]
        if (
            section.get("type") != "sftp"
            or section.get("ssh")
            or section.get("known_hosts_file", "") in {"", "none"}
        ):
            raise ValueError("SFTP with explicit known_hosts verification is required")
        PrivateBackupPath.file(Path(section["known_hosts_file"]))
        if section.getboolean("pin_host_key", fallback=False):
            raise ValueError("unattended trust-on-first-use is forbidden")
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("RCLONE_")
        }

    def command(self, *args: str) -> list[str]:
        return [
            "rclone",
            "--config",
            str(self.config),
            "--contimeout",
            "15s",
            "--timeout",
            "60s",
            "--retries",
            "1",
            "--low-level-retries",
            "1",
            *args,
        ]

    def run(self, *args: str) -> bytes:
        return subprocess.check_output(
            self.command(*args),
            env=self.environment,
            stderr=subprocess.DEVNULL,
            timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
        )

    def checksum(self, name: str) -> str:
        # Read back bytes; do not trust an optional remote shell hash implementation.
        with tempfile.TemporaryFile(dir=self.staging) as output:
            subprocess.run(
                self.command("cat", self.path(name)),
                stdout=output,
                stderr=subprocess.DEVNULL,
                env=self.environment,
                check=True,
                timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
            )
            output.seek(0)
            return hashlib.file_digest(output, "sha256").hexdigest()

    def path(self, name: str) -> str:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("invalid remote artifact name")
        return f"{self.remote}/{name}"

    def upload(self, archive: Path, bundle: Path) -> None:
        identity = ArchiveName.parse(archive.name)
        if identity is None or sha256_file(archive) != identity.checksum:
            raise ValueError("invalid encrypted archive checksum")
        bundle_digest = sha256_file(bundle)
        bundle_name = f"{archive.name}.{bundle_digest}.release.tar.gz"
        self.run("copyto", str(bundle), self.path(bundle_name), "--immutable")
        if self.checksum(bundle_name) != bundle_digest:
            raise RuntimeError("remote release bundle checksum mismatch")
        self.run("copyto", str(archive), self.path(archive.name), "--immutable")
        if self.checksum(archive.name) != identity.checksum:
            raise RuntimeError("remote encrypted archive checksum mismatch")
        archive.unlink()
        self.expire()

    def completed(self) -> list[tuple[str, ArchiveName, str]]:
        rows = json.loads(
            self.run("lsjson", self.remote, "--files-only", "--max-depth", "1")
        )
        names = {row["Name"] for row in rows if not row.get("IsDir")}
        completed = []
        for name in names:
            identity = ArchiveName.parse(name)
            if identity is None:
                continue
            matches = [
                candidate
                for candidate in names
                if re.fullmatch(
                    re.escape(name) + r"\.[a-f0-9]{64}\.release\.tar\.gz", candidate
                )
            ]
            if len(matches) == 1:
                completed.append((name, identity, matches[0]))
        return completed

    def require_recent(self) -> None:
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=RECOVERY_POINT_HOURS)
        for name, identity, bundle in sorted(
            self.completed(), key=lambda item: item[1].snapshot_started_at, reverse=True
        ):
            if (
                cutoff <= identity.snapshot_started_at <= now
                and self.checksum(name) == identity.checksum
                and self.checksum(bundle)
                == bundle.removeprefix(name + ".").split(".")[0]
            ):
                return
        raise RuntimeError("no verified off-server recovery point within policy")

    def expire(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=BACKUP_RETENTION_DAYS)
        rows = json.loads(
            self.run("lsjson", self.remote, "--files-only", "--max-depth", "1")
        )
        for row in rows:
            name = row["Name"]
            # rclone versions with atomic SFTP upload may leave fingerprinted
            # partials after process loss; only our canonical artifact prefix expires.
            completed_name = re.sub(r"\.[a-z0-9]{1,64}\.partial$", "", name)
            archive_name = completed_name
            match = re.fullmatch(
                r"(.+\.dump\.age)\.[a-f0-9]{64}\.release\.tar\.gz", completed_name
            )
            if match:
                archive_name = match[1]
            identity = ArchiveName.parse(archive_name)
            if (
                identity
                and identity.snapshot_started_at <= cutoff
                and not row.get("IsDir")
            ):
                self.run("deletefile", self.path(name))

    def download(self, name: str, destination: Path) -> tuple[Path, Path]:
        directory = PrivateBackupPath.directory(destination)
        matches = [
            (identity, bundle)
            for candidate, identity, bundle in self.completed()
            if candidate == name
        ]
        if len(matches) != 1:
            raise ValueError("archive and matching release bundle are required")
        identity, bundle_name = matches[0]
        archive, bundle = directory / name, directory / "release.tar.gz"
        if archive.exists() or bundle.exists():
            raise ValueError("download destination must not contain these artifacts")
        self.run("copyto", self.path(name), str(archive))
        self.run("copyto", self.path(bundle_name), str(bundle))
        archive.chmod(0o600)
        bundle.chmod(0o600)
        if (
            sha256_file(archive) != identity.checksum
            or sha256_file(bundle) != bundle_name.removeprefix(name + ".").split(".")[0]
        ):
            archive.unlink(missing_ok=True)
            bundle.unlink(missing_ok=True)
            raise RuntimeError("download checksum mismatch")
        return archive, bundle
