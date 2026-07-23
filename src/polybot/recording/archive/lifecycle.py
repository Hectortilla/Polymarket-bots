"""Filesystem, SQLite connection, and lease management for archives."""

from __future__ import annotations

import fcntl
import os
import sqlite3
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO

from .connections import readonly_database_uri
from .errors import ArchiveFormatError, ArchiveLockedError, RecordingArchiveError


def _archive_path(path: str | Path) -> Path:
    if isinstance(path, Path):
        archive_path = path
    elif isinstance(path, str) and path.strip():
        archive_path = Path(path)
    else:
        raise ValueError("recording archive path must not be empty")
    return archive_path.expanduser().resolve()


def _open_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path,
        timeout=0,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _open_readonly_connection(
    path: Path,
    *,
    immutable: bool = False,
) -> sqlite3.Connection:
    uri = readonly_database_uri(path, immutable=immutable)
    try:
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except sqlite3.Error as error:
        raise ArchiveFormatError("could not open recording archive") from error


def _checkpoint_wal(connection: sqlite3.Connection) -> None:
    try:
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except sqlite3.Error as error:
        raise RecordingArchiveError(
            "recording archive WAL could not be checkpointed"
        ) from error
    if result is None or int(result[0]) != 0:
        raise ArchiveLockedError(
            "recording archive has an active reader and cannot be leased for replay"
        )


def _acquire_writer_lock(lock_file: BinaryIO, path: Path) -> None:
    try:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except (BlockingIOError, OSError) as error:
        lock_file.close()
        raise ArchiveLockedError(
            f"recording archive is already open for writing: {path}"
        ) from error


def _open_writer_lock_file(path: Path) -> BinaryIO:
    lock_path = path.with_name(f"{path.name}.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    return os.fdopen(descriptor, "r+b", buffering=0)


def _release_writer_lock(lock_file: BinaryIO) -> None:
    with suppress(OSError, ValueError):
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    with suppress(OSError, ValueError):
        lock_file.close()

