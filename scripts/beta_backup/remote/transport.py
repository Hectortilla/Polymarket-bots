"""Bounded rclone SFTP calls and validated remote directory entries."""

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from polybot.persistence.hashing import SHA256_ALGORITHM

from scripts.beta_backup.policy import BACKUP_PROCESS_TIMEOUT_SECONDS
from scripts.beta_backup.remote.config import SftpRemoteConfig


class RemoteBackupError(RuntimeError):
    """The remote dependency could not establish a verified backup outcome."""


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    is_dir: bool

    @classmethod
    def parse_listing(cls, payload: object) -> tuple["RemoteEntry", ...]:
        if not isinstance(payload, list):
            raise RemoteBackupError("invalid remote artifact listing")
        entries = []
        seen = set()
        for row in payload:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("Name"), str)
                or type(row.get("IsDir")) is not bool
            ):
                raise RemoteBackupError("invalid remote artifact entry")
            name = validate_artifact_name(row["Name"])
            if name in seen:
                raise RemoteBackupError("duplicate remote artifact entry")
            seen.add(name)
            entries.append(cls(name, row["IsDir"]))
        return tuple(entries)


class RcloneSftp:
    def __init__(self, config: SftpRemoteConfig) -> None:
        self.config = config
        # Environment overrides must not redirect the validated remote or host keys.
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("RCLONE_")
        }

    def list_entries(self) -> tuple[RemoteEntry, ...]:
        try:
            payload = json.loads(
                self.run(
                    "lsjson",
                    self.config.directory.remote,
                    "--files-only",
                    "--max-depth",
                    "1",
                )
            )
        except (ValueError, UnicodeError):
            raise RemoteBackupError("invalid remote artifact listing") from None
        return RemoteEntry.parse_listing(payload)

    def checksum(self, artifact_name: str) -> str:
        # Read bytes; an optional remote shell hash cannot establish integrity.
        with tempfile.TemporaryFile(dir=self.config.staging) as output:
            try:
                subprocess.run(
                    self.command("cat", self.remote_artifact_path(artifact_name)),
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    env=self.environment,
                    check=True,
                    timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
                )
            except (OSError, subprocess.SubprocessError):
                raise RemoteBackupError("SFTP artifact readback failed") from None
            output.seek(0)
            return hashlib.file_digest(output, SHA256_ALGORITHM).hexdigest()

    def run(self, *args: str) -> bytes:
        try:
            return subprocess.check_output(
                self.command(*args),
                env=self.environment,
                stderr=subprocess.DEVNULL,
                timeout=BACKUP_PROCESS_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            raise RemoteBackupError(f"SFTP {args[0]} failed") from None

    def remote_artifact_path(self, artifact_name: str) -> str:
        return f"{self.config.directory.remote}/{validate_artifact_name(artifact_name)}"

    def command(self, *args: str) -> list[str]:
        return [
            "rclone",
            "--config",
            str(self.config.path),
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


def validate_artifact_name(name: str) -> str:
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("invalid remote artifact name")
    return name
