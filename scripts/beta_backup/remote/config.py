"""Validated private SFTP configuration for the rclone adapter."""

import configparser
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.beta_backup.paths import PrivateBackupPath

BACKUP_REMOTE_NAME = "backup"
SFTP_BACKEND = "sftp"


@dataclass(frozen=True)
class SftpApplicationDirectory:
    path: str

    @classmethod
    def parse(cls, value: str) -> "SftpApplicationDirectory":
        if (
            not isinstance(value, str)
            or re.fullmatch(r"/[a-zA-Z0-9/_-]+", value) is None
            or value.rstrip("/") in {"", "/backups", "/home"}
        ):
            raise ValueError(
                "a dedicated absolute SFTP application directory is required"
            )
        return cls(value.rstrip("/"))

    @classmethod
    def from_remote(cls, value: str) -> "SftpApplicationDirectory":
        prefix = BACKUP_REMOTE_NAME + ":"
        if not isinstance(value, str) or not value.startswith(prefix):
            raise ValueError("invalid backup remote namespace")
        return cls.parse(value.removeprefix(prefix))

    @property
    def remote(self) -> str:
        return f"{BACKUP_REMOTE_NAME}:{self.path}"


@dataclass(frozen=True)
class SftpRemoteConfig:
    path: Path
    directory: SftpApplicationDirectory
    staging: Path
    host: str
    port: int
    user: str
    key_file: Path

    @classmethod
    def read(cls, config: Path, remote: str, staging: Path) -> "SftpRemoteConfig":
        path = PrivateBackupPath.file(config)
        directory = SftpApplicationDirectory.from_remote(remote)
        settings = configparser.ConfigParser(interpolation=None)
        try:
            settings.read(path)
            section = settings[BACKUP_REMOTE_NAME]
            if (
                section.get("type") != SFTP_BACKEND
                or section.get("ssh")
                or section.get("known_hosts_file", "") in {"", "none"}
            ):
                raise ValueError(
                    "SFTP with explicit known_hosts verification is required"
                )
            PrivateBackupPath.file(Path(section["known_hosts_file"]))
            host = validate_sftp_host(section["host"])
            user = validate_sftp_user(section["user"])
            port = section.getint("port")
            if port is None or not 1 <= port <= 65535:
                raise ValueError("invalid SFTP port")
            key_file = Path(section["key_file"])
            if not key_file.is_absolute():
                raise ValueError("SFTP identity path must be absolute")
            key_file = PrivateBackupPath.file(key_file)
            if section.getboolean("pin_host_key", fallback=False):
                raise ValueError("unattended trust-on-first-use is forbidden")
        except (KeyError, configparser.Error):
            raise ValueError("invalid private SFTP configuration") from None
        return cls(
            path,
            directory,
            PrivateBackupPath.directory(staging),
            host,
            port,
            user,
            key_file,
        )


def validate_sftp_host(value: str) -> str:
    if (
        re.fullmatch(
            r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*",
            value,
        )
        is None
    ):
        raise ValueError("invalid SFTP hostname")
    return value


def validate_sftp_user(value: str) -> str:
    if re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*", value) is None:
        raise ValueError("invalid SFTP username")
    return value
